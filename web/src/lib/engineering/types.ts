import type { CommentReviewDelta } from "@/app/app/services/streamingModels";

export type ReviewStatus =
  | "queued"
  | "running"
  | "ready"
  | "failed"
  | "cancelled";
export type DecisionValue = "accept" | "reject" | "needs_review";
export interface EngineerDecision {
  finding_id: string;
  value: DecisionValue;
  note: string;
  actor_id: string;
  created_at: string;
  version: number;
}
export interface EngineeringReview {
  id: string;
  status: ReviewStatus;
  original_name: string;
  revised_name: string;
  original_sha256: string;
  revised_sha256: string;
  created_at: string;
  updated_at: string;
  attempts: number;
  error: string | null;
  result:
    | (Omit<CommentReviewDelta, "type"> & { type: "comment_review_result" })
    | null;
  decisions: EngineerDecision[];
  version: number;
  pipeline_version: string;
  model_name: string | null;
  page_order_confirmed: boolean;
}
