import { z } from "zod";
import type { PdfAnnotationObject } from "@embedpdf/models";
import type { ReactNode } from "react";
import type {
  CommentVerdict,
  DrawingMarkBox,
} from "@/app/app/services/streamingModels";

const rectSchema = z.object({
  origin: z.object({ x: z.number().finite(), y: z.number().finite() }),
  size: z.object({
    width: z.number().positive(),
    height: z.number().positive(),
  }),
});
const annotationBase = z.object({
  id: z.string(),
  type: z.number().int(),
  pageIndex: z.number().int().nonnegative(),
  rect: rectSchema,
});
export const annotationSchema = z.custom<PdfAnnotationObject>(
  (value) => annotationBase.safeParse(value).success
);
export const anchorSchema = z
  .object({
    page: z.number().int().positive(),
    x: z.number().finite().min(0).max(1),
    y: z.number().finite().min(0).max(1),
    width: z.number().finite().positive().max(1),
    height: z.number().finite().positive().max(1),
  })
  .refine(
    (anchor) =>
      anchor.x + anchor.width <= 1.00001 && anchor.y + anchor.height <= 1.00001
  );
export type ReviewAnchor = z.infer<typeof anchorSchema>;
const recordSchema = z.object({
  annotation: annotationSchema,
  appearance: z.string().nullable().optional(),
  deleted: z.boolean().optional(),
});
export const workspaceSchema = z.object({
  id: z.string(),
  version: z.number(),
  can_undo: z.boolean(),
  can_redo: z.boolean(),
  documents: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      sha256: z.string(),
      pages: z.array(
        z.object({
          width: z.number(),
          height: z.number(),
          rotation: z.number(),
          crop: z.array(z.number()),
        })
      ),
    })
  ),
  state: z.object({
    annotations: z.record(z.string(), z.record(z.string(), recordSchema)),
    anchors: z.record(z.string(), anchorSchema),
    calibrations: z.record(
      z.string(),
      z.object({ units_per_point: z.number(), unit: z.string() })
    ),
  }),
});
export type WorkspaceSnapshot = z.infer<typeof workspaceSchema>;
export interface ReviewDocument {
  id: string;
  url: string;
  filename: string;
  label: string;
  role?: "original" | "revised";
  overlay?: (page: number) => ReactNode;
  selectedPage?: number;
}
export interface LinkedIssue {
  id: string;
  locationIdentity?: string;
  title: string;
  request: string;
  evidence: string;
  remaining: string;
  verdict?: CommentVerdict;
  anchors: Record<
    string,
    {
      page: number;
      box: DrawingMarkBox | null;
      pageLevel: boolean;
      quality?: "confirmed" | "proposed" | "located_text" | "located_comment";
    }
  >;
}
export interface ReviewFocusRequest {
  id: string;
  issueId: string;
  documentId: string;
  page: number;
}

export interface PdfReviewWorkspaceProps {
  documents: ReviewDocument[];
  pageNumber: number;
  onPageChange: (page: number) => void;
  issues?: LinkedIssue[];
  selectedIssueId?: string | null;
  focusRequest?: ReviewFocusRequest | null;
  hoveredIssueId?: string | null;
  onIssueSelect?: (id: string, page: number) => void;
  fill?: boolean;
}
export interface DrawingEdit {
  action:
    | "upsert_annotation"
    | "delete_annotation"
    | "set_anchor"
    | "calibrate"
    | "undo"
    | "redo";
  document_id?: string;
  annotation?: PdfAnnotationObject;
  annotation_id?: string;
  appearance?: string | null;
  issue_id?: string;
  anchor?: ReviewAnchor;
  page?: number;
  units_per_point?: number;
  unit?: string;
}
