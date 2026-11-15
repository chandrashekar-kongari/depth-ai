import { render, screen } from "@tests/setup/test-utils";
import { ParallelStreamingHeader } from "@/app/app/message/messageComponents/timeline/headers/ParallelStreamingHeader";
import {
  Packet,
  PacketType,
  FileReaderToolPacket,
} from "@/app/app/services/streamingModels";
import { getToolIcon } from "@/app/app/message/messageComponents/toolDisplayHelpers";
import { SvgFileText } from "@opal/icons";
import {
  stepHasCollapsedStreamingContent,
  stepSupportsCollapsedStreaming,
} from "@/app/app/message/messageComponents/timeline/packetHelpers";
import { FileReaderToolRenderer } from "@/app/app/message/messageComponents/timeline/renderers/filereader/FileReaderToolRenderer";
import { RenderType } from "@/app/app/message/messageComponents/types";

const placement = { turn_index: 0, tab_index: 0 };
const review: Packet = {
  placement,
  obj: { type: PacketType.COMMENT_REVIEW_START, review_kind: "vision" },
};
const reader: FileReaderToolPacket = {
  placement,
  obj: { type: PacketType.FILE_READER_START },
};
const debug: Packet = {
  placement,
  obj: {
    type: PacketType.TOOL_CALL_DEBUG,
    tool_call_id: "r",
    tool_name: "read_file",
    tool_args: {},
  },
};

test("parallel review and file reads have accurate names and icons even after debug packets", () => {
  render(
    <ParallelStreamingHeader
      steps={[
        { key: "0-0", turnIndex: 0, tabIndex: 0, packets: [review] },
        { key: "0-1", turnIndex: 0, tabIndex: 1, packets: [debug, reader] },
        { key: "0-2", turnIndex: 0, tabIndex: 2, packets: [reader] },
      ]}
      activeTab="0-0"
      onTabChange={jest.fn()}
      collapsible
      isExpanded={false}
      onToggle={jest.fn()}
    />
  );
  expect(
    screen.getByRole("tab", { name: /^Vision review(?: Loading)?$/ })
  ).toBeVisible();
  expect(
    screen.getAllByRole("tab", { name: /^File Reader(?: Loading)?$/ })
  ).toHaveLength(2);
  expect(
    screen.queryByRole("tab", { name: /^Tool(?: Loading)?$/ })
  ).not.toBeInTheDocument();
  expect(getToolIcon([debug, reader])).toBe(SvgFileText);
  for (const packet of [review, reader]) {
    expect(stepSupportsCollapsedStreaming([packet])).toBe(true);
    expect(stepHasCollapsedStreamingContent([packet])).toBe(true);
  }
});

test.each([RenderType.HIGHLIGHT, RenderType.COMPACT])(
  "rejected file reads show a failure instead of a blank body in %s",
  (renderType) => {
    render(
      <FileReaderToolRenderer
        state={{}}
        packets={[
          reader,
          { placement, obj: { type: PacketType.ERROR } },
          { placement, obj: { type: PacketType.SECTION_END } },
        ]}
        renderType={renderType}
        animate={false}
        stopPacketSeen={false}
        onComplete={jest.fn()}
      >
        {(steps) => (
          <>
            {steps[0]?.status}
            {steps[0]?.content}
          </>
        )}
      </FileReaderToolRenderer>
    );
    expect(screen.getByText("File unavailable")).toBeVisible();
    expect(screen.getByText("This file could not be read.")).toBeVisible();
    expect(screen.queryByText("Reading file")).not.toBeInTheDocument();
  }
);

test("historical empty file results also show a failure", () => {
  render(
    <FileReaderToolRenderer
      state={{}}
      packets={[reader, { placement, obj: { type: PacketType.SECTION_END } }]}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen
      onComplete={jest.fn()}
    >
      {(steps) => <>{steps[0]?.content}</>}
    </FileReaderToolRenderer>
  );
  expect(screen.getByText("This file could not be read.")).toBeVisible();
});
