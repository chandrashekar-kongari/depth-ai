"use client";
import { locationKey } from "@/lib/pdf-review/anchors";
import useSWR from "swr";
import { z } from "zod";
import {
  anchorSchema,
  type LinkedIssue,
  type WorkspaceSnapshot,
} from "@/lib/pdf-review/types";
const locationsSchema = z.array(
  z.object({
    id: z.string(),
    status: z.enum([
      "located_text",
      "located_comment",
      "ambiguous",
      "unresolved",
    ]),
    anchor: anchorSchema.nullable(),
    text: z.string().nullable(),
    source: z.literal("pdfplumber"),
    candidate_count: z.number(),
  })
);
export function useTextLocations(
  snapshot: WorkspaceSnapshot | undefined,
  documentId: string,
  issues: LinkedIssue[],
  role: "original" | "revised" = "revised"
) {
  const queries = issues.flatMap((issue) => {
    const source = issue.anchors[documentId];
    if (
      source?.quality === "located_difference" ||
      source?.quality === "located_text"
    )
      return [];
    return source
      ? [
          {
            id: issue.id,
            page: source.page,
            request: issue.request,
            evidence: issue.evidence,
            role,
            source_text: issue.title,
          },
        ]
      : [];
  });
  const body = JSON.stringify({ document_id: documentId, queries });
  const result = useSWR(
    snapshot && queries.length
      ? ["pdf-text-locations", snapshot.id, body]
      : null,
    async ([, id, payload]: string[]) => {
      const response = await fetch(
        `/api/engineering/workspaces/${id}/locations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: payload,
        }
      );
      if (!response.ok) throw new Error("Native PDF locations unavailable");
      return locationsSchema.parse(await response.json());
    },
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  return {
    ...result,
    issues: issues.map((issue) => {
      const location = result.data?.find((item) => item.id === issue.id);
      if (
        !location?.anchor ||
        !["located_text", "located_comment"].includes(location.status)
      )
        return issue;
      const { page, ...box } = location.anchor;
      return {
        ...issue,
        locationIdentity: locationKey(issue),
        anchors: {
          ...issue.anchors,
          [documentId]: {
            page,
            box,
            pageLevel: false,
            quality:
              location.status === "located_comment"
                ? ("located_comment" as const)
                : ("located_text" as const),
          },
        },
      };
    }),
  };
}
