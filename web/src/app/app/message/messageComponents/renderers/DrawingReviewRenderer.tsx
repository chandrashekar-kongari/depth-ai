import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { SvgFileText } from "@opal/icons";
import { Text } from "@opal/components";
import {
  DrawingReviewToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { DrawingSheetMarks } from "@/app/app/message/messageComponents/renderers/DrawingSheetMarks";
import { useDrawingReviewLayout } from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";

function reviewState(packets: DrawingReviewToolPacket[]) {
  const started = packets.some(
    (packet) => packet.obj.type === PacketType.DRAWING_REVIEW_START
  );
  const deltaPacket = packets.find(
    (packet) => packet.obj.type === PacketType.DRAWING_REVIEW_DELTA
  );
  const delta =
    deltaPacket?.obj.type === PacketType.DRAWING_REVIEW_DELTA
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

export const DrawingReviewRenderer: MessageRenderer<
  DrawingReviewToolPacket,
  {}
> = ({ packets, onComplete, renderType, children }) => {
  const t = useTranslations("chat.messages.drawingReview");
  const layoutActive = useDrawingReviewLayout().active;
  const { isRunning, isComplete, failed, delta } = reviewState(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete, onComplete]);

  const status = failed
    ? t("failedStatus.text")
    : isComplete
      ? t("reviewedStatus.text")
      : t("reviewingStatus.text");

  if (
    renderType !== RenderType.FULL ||
    isRunning ||
    delta === null ||
    layoutActive
  ) {
    return children([
      {
        icon: SvgFileText,
        status,
        supportsCollapsible: false,
        content: (
          <Text font="secondary-body" color="text-03">
            {status}
          </Text>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgFileText,
      status,
      supportsCollapsible: true,
      content: (
        <DrawingSheetMarks
          sheetFileId={delta.sheet_file_id}
          sheetFilename={delta.sheet_filename}
          pageCount={delta.page_count}
          findings={delta.findings}
        />
      ),
    },
  ]);
};
