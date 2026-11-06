import type {
  LinkedIssue,
  ReviewAnchor,
  WorkspaceSnapshot,
} from "@/lib/pdf-review/types";

export function resolvedAnchor(
  snapshot: WorkspaceSnapshot | undefined,
  documentId: string,
  issue: LinkedIssue
): ReviewAnchor | null {
  const saved = snapshot?.state.anchors[`${documentId}:${locationKey(issue)}`];
  if (saved) return saved;
  const original = issue.anchors[documentId];
  if (
    !original?.box ||
    original.pageLevel ||
    (original.quality !== "confirmed" &&
      original.quality !== "located_text" &&
      original.quality !== "located_comment")
  )
    return null;
  return { page: original.page, ...original.box };
}

/** Legacy sequential IDs alone cannot identify a finding across repeated reviews. */
export function locationKey(issue: LinkedIssue): string {
  if (issue.locationIdentity) return issue.locationIdentity;
  const text = JSON.stringify([
    issue.id,
    issue.title,
    issue.request,
    issue.anchors,
  ]);
  let first = 2166136261,
    second = 5381;
  for (const character of text) {
    first = Math.imul(first ^ character.charCodeAt(0), 16777619);
    second = Math.imul(second, 33) ^ character.charCodeAt(0);
  }
  return `v2:${issue.id}:${(first >>> 0).toString(16)}${(second >>> 0).toString(16)}`;
}
