import React, { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  PacketType,
  ReasoningPacket,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  FullChatState,
} from "@/app/app/message/messageComponents/types";
import { SvgCircle } from "@opal/icons";

const THINKING_MIN_DURATION_MS = 500; // 0.5 second minimum for "Thinking" state

export const ReasoningRenderer: MessageRenderer<
  ReasoningPacket,
  FullChatState
> = ({ packets, onComplete, animate, children }) => {
  const t = useTranslations("chat.messages.timeline");
  const thinkingStatus = t("header.thinkingEllipsis.label");
  const hasStart = packets.some(
    (packet) => packet.obj.type === PacketType.REASONING_START
  );
  const hasEnd = packets.some(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR ||
      packet.obj.type === PacketType.REASONING_DONE
  );

  // Track reasoning timing for minimum display duration
  const [reasoningStartTime, setReasoningStartTime] = useState<number | null>(
    null
  );
  const completionHandledRef = useRef(false);

  // Track when reasoning starts
  useEffect(() => {
    if ((hasStart || hasEnd) && reasoningStartTime === null) {
      setReasoningStartTime(Date.now());
    }
  }, [hasStart, hasEnd, reasoningStartTime]);

  // Handle reasoning completion with minimum duration
  useEffect(() => {
    if (
      !hasEnd ||
      reasoningStartTime === null ||
      completionHandledRef.current
    ) {
      return;
    }

    const complete = () => {
      if (!completionHandledRef.current) {
        completionHandledRef.current = true;
        onComplete();
      }
    };

    const elapsedTime = Date.now() - reasoningStartTime;
    const minimumThinkingDuration = animate ? THINKING_MIN_DURATION_MS : 0;

    if (elapsedTime >= minimumThinkingDuration) {
      complete();
      return;
    }

    const remainingTime = minimumThinkingDuration - elapsedTime;
    const timeout = setTimeout(complete, remainingTime);
    return () => clearTimeout(timeout);
  }, [hasEnd, reasoningStartTime, animate, onComplete]);

  return children([
    {
      icon: SvgCircle,
      status: thinkingStatus,
      content: <></>,
      noPaddingRight: true,
    },
  ]);
};

export default ReasoningRenderer;
