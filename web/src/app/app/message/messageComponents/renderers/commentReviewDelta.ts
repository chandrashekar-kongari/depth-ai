import type { Message } from "@/app/app/types";
import {
  PacketType,
  type CommentReviewDelta,
  type DrawingReviewDelta,
  type Packet,
} from "@/app/app/services/streamingModels";
import { completedDrawingReviewFromPackets } from "@/app/app/message/messageComponents/renderers/drawingReviewDelta";

function groupKey(packet: Packet): string {
  return `${packet.placement.turn_index}:${packet.placement.tab_index ?? 0}`;
}

function packetsByTurn(packets: Packet[]): Map<string, Packet[]> {
  const groups = new Map<string, Packet[]>();
  for (const packet of packets) {
    const key = groupKey(packet);
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, [packet]);
    } else {
      group.push(packet);
    }
  }
  return groups;
}

function completedDelta(group: Packet[]): CommentReviewDelta | null {
  const started = group.some(
    (packet) => packet.obj.type === PacketType.COMMENT_REVIEW_START
  );
  const ended = group.some(
    (packet) => packet.obj.type === PacketType.SECTION_END
  );
  const failed = group.some((packet) => packet.obj.type === PacketType.ERROR);
  if (!started || !ended || failed) {
    return null;
  }
  let delta: CommentReviewDelta | null = null;
  for (const packet of group) {
    if (packet.obj.type === PacketType.COMMENT_REVIEW_DELTA) {
      delta = packet.obj;
    }
  }
  return delta;
}

export function completedCommentReviewFromPackets(
  packets: Packet[]
): CommentReviewDelta | null {
  let latest: CommentReviewDelta | null = null;
  for (const group of packetsByTurn(packets).values()) {
    const delta = completedDelta(group);
    if (delta !== null) {
      latest = delta;
    }
  }
  return latest;
}

export type SheetFocus =
  | { kind: "checklist"; review: DrawingReviewDelta }
  | { kind: "comments"; review: CommentReviewDelta };

function lastPacketIndex(packets: Packet[], type: PacketType): number {
  let index = -1;
  packets.forEach((packet, packetIndex) => {
    if (packet.obj.type === type) {
      index = packetIndex;
    }
  });
  return index;
}

export function latestSheetFocus(
  messages: readonly Message[]
): SheetFocus | null {
  let latest: SheetFocus | null = null;
  for (const message of messages) {
    const checklist = completedDrawingReviewFromPackets(message.packets);
    const comments = completedCommentReviewFromPackets(message.packets);
    const reviewIndex = lastPacketIndex(
      message.packets,
      PacketType.DRAWING_REVIEW_DELTA
    );
    const commentIndex = lastPacketIndex(
      message.packets,
      PacketType.COMMENT_REVIEW_DELTA
    );
    if (
      checklist !== null &&
      (comments === null || reviewIndex > commentIndex)
    ) {
      latest = { kind: "checklist", review: checklist };
    }
    if (
      comments !== null &&
      (checklist === null || commentIndex >= reviewIndex)
    ) {
      latest = { kind: "comments", review: comments };
    }
  }
  return latest;
}
