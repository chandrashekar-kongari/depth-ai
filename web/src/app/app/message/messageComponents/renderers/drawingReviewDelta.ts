import type { Message } from "@/app/app/types";
import {
  PacketType,
  type DrawingReviewDelta,
  type Packet,
} from "@/app/app/services/streamingModels";

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

function completedDelta(group: Packet[]): DrawingReviewDelta | null {
  const started = group.some(
    (packet) => packet.obj.type === PacketType.DRAWING_REVIEW_START
  );
  const ended = group.some(
    (packet) => packet.obj.type === PacketType.SECTION_END
  );
  const failed = group.some((packet) => packet.obj.type === PacketType.ERROR);
  if (!started || !ended || failed) {
    return null;
  }
  let delta: DrawingReviewDelta | null = null;
  for (const packet of group) {
    if (packet.obj.type === PacketType.DRAWING_REVIEW_DELTA) {
      delta = packet.obj;
    }
  }
  return delta;
}

export function completedDrawingReviewFromPackets(
  packets: Packet[]
): DrawingReviewDelta | null {
  let latest: DrawingReviewDelta | null = null;
  for (const group of packetsByTurn(packets).values()) {
    const delta = completedDelta(group);
    if (delta !== null) {
      latest = delta;
    }
  }
  return latest;
}

export function latestCompletedDrawingReview(
  messages: readonly Message[]
): DrawingReviewDelta | null {
  let latest: DrawingReviewDelta | null = null;
  for (const message of messages) {
    const delta = completedDrawingReviewFromPackets(message.packets);
    if (delta !== null) {
      latest = delta;
    }
  }
  return latest;
}
