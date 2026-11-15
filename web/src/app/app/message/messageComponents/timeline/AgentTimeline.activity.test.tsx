import { render } from "@tests/setup/test-utils";
import { useReducedMotion } from "motion/react";
import { AgentTimeline } from "@/app/app/message/messageComponents/timeline/AgentTimeline";
import { StopReason } from "@/app/app/services/streamingModels";
import type { MinimalAgent } from "@/lib/agents/types";

jest.mock(
  "@/app/app/message/messageComponents/timeline/ExpandedTimelineContent",
  () => ({ ExpandedTimelineContent: () => null })
);
jest.mock(
  "@/app/app/message/messageComponents/timeline/CollapsedStreamingContent",
  () => ({ CollapsedStreamingContent: () => null })
);

jest.mock("motion/react", () => ({
  ...jest.requireActual<typeof import("motion/react")>("motion/react"),
  useReducedMotion: jest.fn(),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ enterprise: undefined }),
}));

const agent: MinimalAgent = {
  id: 0,
  name: "Depth",
  description: "",
  tools: [],
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: true,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

beforeEach(() => jest.mocked(useReducedMotion).mockReturnValue(false));

test.each([StopReason.FINISHED, StopReason.USER_CANCELLED])(
  "the real timeline stops its working icon on %s",
  (stopReason) => {
    const { container, rerender } = render(
      <AgentTimeline turnGroups={[]} chatState={{ agent }} />
    );
    expect(container.querySelector("[data-depth-pulse]")).not.toBeNull();
    rerender(
      <AgentTimeline
        turnGroups={[]}
        chatState={{ agent }}
        stopReason={stopReason}
      />
    );
    expect(container.querySelector("[data-depth-pulse]")).toBeNull();
  }
);

test("a terminal stream packet freezes the icon even without a stop reason", () => {
  const { container } = render(
    <AgentTimeline turnGroups={[]} chatState={{ agent }} stopPacketSeen />
  );
  expect(container.querySelector("[data-depth-pulse]")).toBeNull();
});

test("custom agents keep their own avatar", () => {
  const { container } = render(
    <AgentTimeline
      turnGroups={[]}
      chatState={{ agent: { ...agent, id: 42 } }}
    />
  );
  expect(container.querySelector("[data-depth-activity]")).toBeNull();
});
