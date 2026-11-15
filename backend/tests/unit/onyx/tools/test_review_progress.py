"""Review activity crosses the runtime and chat stream before a tool finishes."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from onyx.agents.runtime import Agent
from onyx.agents.tools import AgentTool, ToolInvocation, ToolProgress
from onyx.chat.emitter import Emitter
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.renderer import ToolRenderer
from onyx.chat.stream_buffer import ChatDelivery, StreamBufferWriter, read_stream_chunks
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CommentReviewStart,
    Packet,
    ReviewProgress,
    SectionEnd,
)
from onyx.tools.models import VisionReviewProgress
from onyx.tracing.flows import LLMFlow
from tests.unit.fakes import FakeCache
from tests.unit.onyx.agents.fakes import FakeModelClient


@pytest.mark.parametrize("fails", [False, True])
def test_review_activity_is_delivered_before_tool_completion(fails: bool) -> None:
    release = threading.Event()
    completed = threading.Event()
    replay_ready = threading.Event()
    session_id = uuid4()

    class ReplayCache(FakeCache):
        def set(
            self, key: str, value: str | bytes | int | float, ex: int | None = None
        ) -> None:
            super().set(key, value, ex)
            if key.endswith(":meta"):
                replay = read_stream_chunks(self, session_id, 1, cursor=0)
                if replay and '"review_progress"' in "".join(replay.blocks):
                    replay_ready.set()

    cache = ReplayCache()
    delivery = ChatDelivery(
        StreamBufferWriter(cache=cache, chat_session_id=session_id, stream_id=1)
    )
    presenter = ResponsePresenter(Emitter(delivery.publish))

    def execute(invocation: ToolInvocation) -> ToolResult:
        invocation.update(
            ToolProgress(details=VisionReviewProgress(stage="reading_original"))
        )
        assert release.wait(10), "Test must observe progress before releasing review"
        completed.set()
        return ToolResult(content="review complete", is_error=fails)

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            return AssistantMessage(content=[TextContent(text="Done")])
        return AssistantMessage(
            content=[
                ToolCall(
                    id="review",
                    name="review_with_vision",
                    arguments={"file_id": "original"},
                )
            ]
        )

    agent = Agent(
        FakeModelClient(reply),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            AgentTool(
                definition=ToolDefinition(
                    name="review_with_vision", description="", parameters={}
                ),
                execute=execute,
            )
        ],
    )
    run = agent.start(
        max_steps=2,
        messages=[],
        on_event=presenter.consume,
        event_dispatcher=delivery.events,
    )
    received: list[Packet] = []
    try:
        with ThreadPoolExecutor(max_workers=1) as reader:
            for _ in range(20):
                part = reader.submit(next, delivery.reader).result(timeout=5)
                if isinstance(part, Packet):
                    received.append(part)
                    if isinstance(part.obj, ReviewProgress):
                        assert part.obj.stage == "reading_original"
                        break
            else:
                pytest.fail("No progress reached the stream")
        assert replay_ready.wait(5), (
            "Progress must be replayable while review is blocked"
        )
        replay = read_stream_chunks(cache, session_id, 1, cursor=0)
        assert replay is not None and not replay.done and not replay.gap
        replayed = [
            Packet.model_validate(json.loads(line))
            for line in "".join(replay.blocks).splitlines()
        ]
        assert any(isinstance(packet.obj, ReviewProgress) for packet in replayed)
        assert not completed.is_set()
        assert any(isinstance(packet.obj, CommentReviewStart) for packet in received)
        assert not any(isinstance(packet.obj, SectionEnd) for packet in received)
    finally:
        release.set()
        run.result(timeout=10)
        assert run.wait_for_idle(timeout=5)
        delivery.finish()
    assert completed.is_set()
    terminal_packets = [part for part in delivery.reader if isinstance(part, Packet)]
    assert any(packet.obj.type == "error" for packet in terminal_packets) is fails
    assert any(isinstance(packet.obj, SectionEnd) for packet in terminal_packets)


def test_review_progress_is_separate_deduplicated_and_terminal() -> None:
    renderer = ToolRenderer(
        ToolCall(id="r", name="review_with_vision", arguments={}),
        Placement(turn_index=0),
    )
    assert isinstance(renderer.start()[0].obj, CommentReviewStart)
    progress = VisionReviewProgress(stage="matching")
    assert isinstance(renderer.update(progress)[0].obj, ReviewProgress)
    assert renderer.update(progress) == []
    assert renderer.complete(ToolResult(content="done"))[-1].obj.type == "section_end"
    assert renderer.update(VisionReviewProgress(stage="checking_changes")) == []


def test_rejected_file_read_emits_a_terminal_error() -> None:
    renderer = ToolRenderer(
        ToolCall(id="read", name="read_file", arguments={}), Placement(turn_index=0)
    )
    output = renderer.complete(
        ToolResult(content="Private file access detail", is_error=True)
    )
    assert [packet.obj.type for packet in output] == [
        "file_reader_start",
        "error",
        "section_end",
    ]
    assert "Private file access detail" not in "".join(
        packet.model_dump_json() for packet in output
    )
