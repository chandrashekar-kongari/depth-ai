import {
  Packet,
  PacketType,
  ReviewStage,
} from "@/app/app/services/streamingModels";

/** Ordered stage snapshots; replay cannot duplicate rows or reopen a finished call. */
export function reviewActivity(packets: readonly Packet[]) {
  const stages: ReviewStage[] = [];
  let ended = false;
  for (const packet of packets) {
    if (
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
    ) {
      ended = true;
    } else if (!ended && packet.obj.type === PacketType.REVIEW_PROGRESS) {
      const previous = stages.indexOf(packet.obj.stage);
      if (previous !== -1) stages.splice(previous, 1);
      stages.push(packet.obj.stage);
    }
  }
  return { stages, activeStage: ended ? undefined : stages.at(-1), ended };
}
