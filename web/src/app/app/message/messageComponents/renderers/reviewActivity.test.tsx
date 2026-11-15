import { render, screen } from "@tests/setup/test-utils";
import { Text } from "@opal/components";
import {
  Packet,
  PacketType,
  CommentReviewToolPacket,
  StopReason,
} from "@/app/app/services/streamingModels";
import {
  createInitialState,
  processPackets,
} from "@/app/app/message/messageComponents/timeline/hooks/packetProcessor";
import {
  groupStepsByTurn,
  transformPacketGroups,
} from "@/app/app/message/messageComponents/timeline/transformers";
import { usePacedTurnGroups } from "@/app/app/message/messageComponents/timeline/hooks/usePacedTurnGroups";
import { useTimelineHeader } from "@/app/app/message/messageComponents/timeline/hooks/useTimelineHeader";
import { CommentReviewRenderer } from "@/app/app/message/messageComponents/renderers/CommentReviewRenderer";
import { RenderType } from "@/app/app/message/messageComponents/types";
import { TOOL_START_PACKET_TYPES } from "@/app/app/services/packetUtils";
import { reviewActivity } from "@/app/app/message/messageComponents/renderers/reviewActivity";

jest.mock("@/lib/pdf-review/PdfReviewWorkspace", () => ({
  PdfReviewWorkspace: () => null,
}));

const placement = { turn_index: 1, tab_index: 0 };
const start: CommentReviewToolPacket = {
  placement,
  obj: { type: PacketType.COMMENT_REVIEW_START },
};
const reading: CommentReviewToolPacket = {
  placement,
  obj: { type: PacketType.REVIEW_PROGRESS, stage: "reading_original" },
};
const matching: CommentReviewToolPacket = {
  placement,
  obj: { type: PacketType.REVIEW_PROGRESS, stage: "matching" },
};
const end: CommentReviewToolPacket = {
  placement,
  obj: { type: PacketType.SECTION_END },
};

function Harness({ packets }: { packets: Packet[] }) {
  const state = processPackets(createInitialState(1), packets);
  const groups = groupStepsByTurn(transformPacketGroups(state.toolGroups));
  const { pacedTurnGroups } = usePacedTurnGroups(groups, [], false, 1, false);
  const { headerText } = useTimelineHeader(pacedTurnGroups);
  const step = pacedTurnGroups
    .flatMap((group) => group.steps)
    .find((step) =>
      step.packets.some(
        (packet) => packet.obj.type === PacketType.COMMENT_REVIEW_START
      )
    );
  const reviewPackets = step?.packets.filter(
    (packet): packet is CommentReviewToolPacket =>
      packet.obj.type === PacketType.COMMENT_REVIEW_START ||
      packet.obj.type === PacketType.REVIEW_PROGRESS ||
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );
  return (
    <>
      <Text>{headerText}</Text>
      {reviewPackets && (
        <CommentReviewRenderer
          packets={reviewPackets}
          state={{}}
          onComplete={() => {}}
          renderType={RenderType.FULL}
          animate={false}
          stopPacketSeen={false}
        >
          {(steps) => <>{steps[0]?.content}</>}
        </CommentReviewRenderer>
      )}
    </>
  );
}

test("shows live stages through grouping, pacing, header and renderer before review results", async () => {
  const reasoning: Packet[] = [
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: PacketType.REASONING_START },
    },
    {
      placement: { turn_index: 0, tab_index: 0 },
      obj: { type: PacketType.SECTION_END },
    },
  ];
  const { rerender } = render(
    <Harness packets={[...reasoning, start, reading]} />
  );
  expect(
    await screen.findAllByText("Reading the original drawing")
  ).toHaveLength(2);
  expect(screen.queryByText("Review summary")).not.toBeInTheDocument();
  rerender(<Harness packets={[...reasoning, start, reading, matching]} />);
  expect(await screen.findAllByText("Matching the drawings")).toHaveLength(2);
  expect(screen.getByText("Reading the original drawing")).toBeVisible();
});

test("replay is idempotent and late activity cannot reopen completed or failed reviews", () => {
  expect(reviewActivity([start, reading, reading, matching]).stages).toEqual([
    "reading_original",
    "matching",
  ]);
  for (const terminal of [
    end,
    { placement, obj: { type: PacketType.ERROR } } satisfies Packet,
  ]) {
    const activity = reviewActivity([start, reading, terminal, matching]);
    expect(activity.activeStage).toBeUndefined();
    expect(activity.stages).toEqual(["reading_original"]);
    expect(activity.ended).toBe(true);
  }
});

test("review packets survive the same classification used by the real timeline", () => {
  const processed = processPackets(createInitialState(1), [start, reading]);
  expect(processed.toolGroups).toHaveLength(1);
  expect(processed.toolGroups[0]?.packets).toEqual([start, reading]);
});

test("every primary tool start is covered by the shared timeline definition", () => {
  const starts = Object.values(PacketType).filter(
    (type) =>
      type.endsWith("_start") &&
      type !== PacketType.MESSAGE_START &&
      type !== PacketType.CITATION_START &&
      type !== PacketType.INTERMEDIATE_REPORT_START
  );
  for (const type of starts)
    expect(TOOL_START_PACKET_TYPES.has(type)).toBe(true);
});

function HeaderOnly({
  packets,
  stopped,
}: {
  packets: Packet[];
  stopped?: StopReason;
}) {
  const state = processPackets(createInitialState(1), packets);
  const groups = groupStepsByTurn(transformPacketGroups(state.toolGroups));
  const { headerText } = useTimelineHeader(groups, stopped);
  return <Text>{headerText}</Text>;
}

test("finishing one parallel review preserves the other review's active stage", () => {
  const second = { turn_index: 1, tab_index: 1 };
  const packets: Packet[] = [
    start,
    reading,
    { ...start, placement: second },
    { ...matching, placement: second },
  ];
  const { rerender } = render(<HeaderOnly packets={packets} />);
  expect(screen.getByText("Matching the drawings")).toBeVisible();
  rerender(
    <HeaderOnly packets={[...packets, { ...end, placement: second }]} />
  );
  expect(screen.getByText("Reading the original drawing")).toBeVisible();
  rerender(
    <HeaderOnly packets={packets} stopped={StopReason.USER_CANCELLED} />
  );
  expect(screen.queryByText("Matching the drawings")).not.toBeInTheDocument();
});
