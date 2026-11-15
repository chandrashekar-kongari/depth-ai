import { reviewActivity } from "@/app/app/message/messageComponents/renderers/reviewActivity";
import { Section } from "@opal/layouts";
import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { SvgFileText } from "@opal/icons";
import { Text } from "@opal/components";
import {
  PacketType,
  type CommentReviewToolPacket,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import {
  DrawingReviewLayoutProvider,
  useDrawingReviewLayout,
} from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";
import { CommentReviewView } from "@/app/app/message/messageComponents/renderers/CommentReviewView";

function reviewState(packets: CommentReviewToolPacket[]) {
  const started = packets.some(
    (packet) => packet.obj.type === PacketType.COMMENT_REVIEW_START
  );
  const deltaPacket = packets.findLast(
    (packet) => packet.obj.type === PacketType.COMMENT_REVIEW_DELTA
  );
  const delta =
    deltaPacket?.obj.type === PacketType.COMMENT_REVIEW_DELTA
      ? deltaPacket.obj
      : null;
  const ended = packets.some(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  );
  const failed = packets.some((packet) => packet.obj.type === PacketType.ERROR);
  return {
    isRunning: started && !ended,
    isComplete: started && ended,
    failed,
    delta,
  };
}

export const CommentReviewRenderer: MessageRenderer<
  CommentReviewToolPacket,
  {}
> = ({ packets, onComplete, renderType, children }) => {
  const t = useTranslations("chat.messages.commentReview");
  const layout = useDrawingReviewLayout();
  const tProgress = useTranslations("chat.messages.reviewProgress");
  const activity = reviewActivity(packets);
  const { isRunning, isComplete, failed, delta } = reviewState(packets);
  const wideComments = layout.active && layout.mode === "comments";

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const status = failed
    ? t("failedStatus.text")
    : isComplete
      ? t("checkedStatus.text")
      : activity.activeStage
        ? tProgress(activity.activeStage)
        : t("checkingStatus.text");

  if (
    renderType !== RenderType.FULL ||
    delta === null ||
    (wideComments && !isRunning)
  ) {
    return children([
      {
        icon: SvgFileText,
        status,
        supportsCollapsible: activity.stages.length > 0,
        content: (
          <Section alignItems="start" gap={2}>
            {activity.stages.length > 0 ? (
              activity.stages.map((stage) => (
                <Text key={stage} font="secondary-body" color="text-03">
                  {tProgress(stage)}
                </Text>
              ))
            ) : (
              <Text font="secondary-body" color="text-03">
                {status}
              </Text>
            )}
          </Section>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgFileText,
      status,
      supportsCollapsible: !isRunning,
      content: (
        <DrawingReviewLayoutProvider
          active
          mode="comments"
          reviewKey={`${delta.commented_sheet_file_id}:${delta.revised_sheet_file_id}`}
        >
          <CommentReviewView review={delta} />
        </DrawingReviewLayoutProvider>
      ),
    },
  ]);
};
