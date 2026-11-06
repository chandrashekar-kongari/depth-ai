"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { LinkedIssue, ReviewFocusRequest } from "@/lib/pdf-review/types";
import { PdfReviewWorkspace } from "@/lib/pdf-review/PdfReviewWorkspace";
import type {
  CommentReviewDelta,
  CommentVerdict,
  DrawingComment,
  DrawingExtraIssue,
} from "@/app/app/services/streamingModels";
import { useDrawingReviewLayout } from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";

interface CommentReviewViewProps {
  fileUrl?: (fileId: string) => string;
  review: CommentReviewDelta;
  part?: "all" | "queue" | "sheets";
  fill?: boolean;
}

function verdictLabel(
  verdict: CommentVerdict,
  t: ReturnType<typeof useTranslations<"chat.messages.commentReview">>
): string {
  switch (verdict) {
    case "open":
      return t("openStatus.label");
    case "solved_correct":
      return t("solvedCorrectStatus.label");
    case "solved_incorrect":
      return t("solvedIncorrectStatus.label");
    default:
      return t("unclearStatus.label");
  }
}

export function CommentReviewView({
  review,
  fileUrl,
  part = "all",
  fill = false,
}: CommentReviewViewProps) {
  const t = useTranslations("chat.messages.commentReview");
  const layout = useDrawingReviewLayout();
  const [localPage, setLocalPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<ReviewFocusRequest | null>(
    null
  );
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const hover = layout.active ? layout.setHoveredId : setHoveredId;
  return (
    <Section
      flexDirection="column"
      alignItems="stretch"
      justifyContent="start"
      gap={2}
      height={fill ? "full" : undefined}
      className="min-h-0"
    >
      {part !== "sheets" ? (
        <CommentQueue
          review={review}
          onHover={hover}
          onShow={(comment, documentId, page) => {
            setSelectedId(comment.id);
            setLocalPage(page);
            if (layout.active) layout.focusIssue(comment.id, documentId, page);
            else
              setFocusRequest({
                id: crypto.randomUUID(),
                issueId: comment.id,
                documentId,
                page,
              });
          }}
          onSelected={(comment) => {
            setSelectedId(comment.id);
            setLocalPage(comment.page);
          }}
        />
      ) : null}
      {part !== "queue" ? (
        <PdfReviewWorkspace
          key={`${review.commented_sheet_file_id}:${review.revised_sheet_file_id}`}
          fill={fill}
          pageNumber={layout.active ? layout.pageNumber : localPage}
          onPageChange={layout.active ? layout.setPageNumber : setLocalPage}
          focusRequest={layout.active ? layout.focusRequest : focusRequest}
          selectedIssueId={layout.active ? layout.selectedId : selectedId}
          hoveredIssueId={layout.active ? layout.hoveredId : hoveredId}
          onIssueSelect={(id, page) => {
            if (layout.active) layout.selectFinding(id, page);
            else {
              setSelectedId(id);
              setLocalPage(page);
            }
          }}
          issues={[
            ...(review.comments ?? []).map((comment) => {
              const anchors: LinkedIssue["anchors"] = {};
              if (review.commented_sheet_file_id)
                anchors[review.commented_sheet_file_id] = {
                  page: comment.page,
                  box: comment.box,
                  pageLevel: comment.page_level,
                };
              if (review.revised_sheet_file_id)
                anchors[review.revised_sheet_file_id] = {
                  page: comment.revised_page ?? comment.page,
                  box: comment.revised_box,
                  pageLevel: comment.revised_page_level,
                };
              return {
                id: comment.id,
                title: comment.text,
                request: comment.request,
                evidence: comment.evidence,
                remaining: comment.remaining,
                verdict: comment.verdict,
                anchors,
              };
            }),
            ...(review.extra_issues ?? []).map(
              (issue): LinkedIssue => ({
                id: issue.id,
                title: issue.title,
                request: issue.detail,
                evidence: issue.detail,
                remaining: issue.detail,
                verdict: "open",
                anchors: review.revised_sheet_file_id
                  ? {
                      [review.revised_sheet_file_id]: {
                        page: issue.page,
                        box: issue.box,
                        pageLevel: issue.page_level,
                      },
                    }
                  : {},
              })
            ),
          ]}
          documents={[
            {
              id: review.commented_sheet_file_id,
              filename: review.commented_sheet_filename,
              label: t("markedSheet.label"),
              role: "original" as const,
            },
            {
              id: review.revised_sheet_file_id,
              filename: review.revised_sheet_filename,
              label: t("newSheet.label"),
              role: "revised" as const,
            },
          ].flatMap((document) =>
            document.id
              ? [
                  {
                    id: document.id,
                    filename: document.filename ?? "drawing.pdf",
                    label: document.label,
                    role: document.role,
                    url:
                      fileUrl?.(document.id) ??
                      `/api/chat/file/${encodeURIComponent(document.id)}`,
                  },
                ]
              : []
          )}
        />
      ) : null}
    </Section>
  );
}

function CommentQueue({
  review,
  onHover,
  onSelected,
  onShow,
}: {
  review: CommentReviewDelta;
  onHover: (id: string | null) => void;
  onSelected: (comment: DrawingComment) => void;
  onShow: (comment: { id: string }, documentId: string, page: number) => void;
}) {
  const t = useTranslations("chat.messages.commentReview");
  const pdfT = useTranslations("chat.messages.pdfWorkspace");
  const layout = useDrawingReviewLayout();
  const [localSelectedId, setLocalSelectedId] = useState<string | null>(null);
  const selectedId = layout.active ? layout.selectedId : localSelectedId;

  function selectComment(comment: DrawingComment) {
    onSelected(comment);
    if (layout.active) {
      layout.selectFinding(comment.id, comment.page);
      return;
    }
    setLocalSelectedId(comment.id);
  }

  return (
    <Section
      flexDirection="column"
      alignItems="stretch"
      justifyContent="start"
      gap={2}
      width="full"
    >
      {review.vision_model ? (
        <Text font="secondary-body" color="text-03">
          {pdfT("visionModel", { model: review.vision_model })}
        </Text>
      ) : null}
      <Text font="secondary-body" color="text-03">
        {pdfT("reviewCoverage", {
          total: (review.comments ?? []).length,
          unclear: (review.comments ?? []).filter(
            (item) => item.verdict === "unclear"
          ).length,
        })}
      </Text>
      {(review.comments ?? []).length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("noComments.text")}
        </Text>
      ) : null}
      {(review.comments ?? []).map((comment, index) => (
        <Card
          key={comment.id}
          border="solid"
          padding={3}
          borderColor={
            comment.verdict === "solved_correct"
              ? "success"
              : comment.verdict === "unclear"
                ? "warning"
                : "error"
          }
          data-issue-id={comment.id}
          aria-current={selectedId === comment.id ? "true" : undefined}
          onPointerEnter={() => onHover(comment.id)}
          onPointerLeave={() => onHover(null)}
          onFocus={() => onHover(comment.id)}
          onBlur={() => onHover(null)}
        >
          <Section
            height="fit"
            justifyContent="start"
            alignItems="stretch"
            gap={2}
          >
            <Section
              flexDirection="row"
              justifyContent="between"
              height="fit"
              gap={2}
            >
              <Text font="secondary-body" color="text-02">
                {pdfT("findingNumber", { number: index + 1 })}
              </Text>
              <Text font="secondary-body" color="text-03">
                {verdictLabel(comment.verdict, t)}
              </Text>
            </Section>
            <Button
              width="full"
              size="sm"
              prominence="tertiary"
              aria-pressed={selectedId === comment.id}
              onClick={() => selectComment(comment)}
            >
              {comment.text}
            </Button>
            <Text font="secondary-body" color="text-03">
              {t("request.text", { request: comment.request })}
            </Text>
            <Text font="secondary-body" color="text-03">
              {t("evidence.text", { evidence: comment.evidence })}
            </Text>
            {!comment.box ||
            comment.page_level ||
            !comment.revised_box ||
            comment.revised_page_level ? (
              <Text font="secondary-body" color="text-03">
                {pdfT("locationUnconfirmed")}
              </Text>
            ) : null}
            {comment.review_attempts ? (
              <Text font="secondary-body" color="text-03">
                {pdfT("reviewPasses", { count: comment.review_attempts })}
              </Text>
            ) : null}
            {comment.remaining ? (
              <Text font="secondary-body" color="text-03">
                {t("remaining.text", { remaining: comment.remaining })}
              </Text>
            ) : null}
            <Section
              flexDirection="row"
              justifyContent="start"
              height="fit"
              gap={2}
              wrap
            >
              <Button
                size="sm"
                prominence="secondary"
                disabled={!review.commented_sheet_file_id}
                onClick={() => {
                  if (review.commented_sheet_file_id)
                    onShow(
                      comment,
                      review.commented_sheet_file_id,
                      comment.page
                    );
                }}
              >
                {pdfT("showOriginal")}
              </Button>
              <Button
                size="sm"
                prominence="secondary"
                disabled={!review.revised_sheet_file_id}
                onClick={() => {
                  if (review.revised_sheet_file_id)
                    onShow(
                      comment,
                      review.revised_sheet_file_id,
                      comment.revised_page ?? comment.page
                    );
                }}
              >
                {pdfT("showRevised")}
              </Button>
            </Section>
          </Section>
        </Card>
      ))}
      {(review.extra_issues ?? []).length > 0 ? (
        <Text font="secondary-body" color="text-02">
          {t("otherIssues.text")}
        </Text>
      ) : null}
      {(review.extra_issues ?? []).map((issue, index) => (
        <ExtraIssueRow
          key={issue.id}
          issue={issue}
          number={(review.comments ?? []).length + index + 1}
          originalId={review.commented_sheet_file_id}
          revisedId={review.revised_sheet_file_id}
          onShow={onShow}
        />
      ))}
    </Section>
  );
}

function ExtraIssueRow({
  issue,
  number,
  originalId,
  revisedId,
  onShow,
}: {
  issue: DrawingExtraIssue;
  number: number;
  originalId: string | null;
  revisedId: string | null;
  onShow: (issue: { id: string }, documentId: string, page: number) => void;
}) {
  const t = useTranslations("chat.messages.commentReview");
  const pdfT = useTranslations("chat.messages.pdfWorkspace");
  return (
    <Card border="solid" padding={3} borderColor="error">
      <Section
        flexDirection="column"
        alignItems="stretch"
        justifyContent="start"
        gap={1}
        width="full"
      >
        <Text font="secondary-body" color="text-03">
          {pdfT("findingNumber", { number })}
        </Text>
        <Text font="secondary-body" color="text-02">
          {issue.title}
        </Text>
        <Text font="secondary-body" color="text-03">
          {t("issueDetail.text", { detail: issue.detail, page: issue.page })}
        </Text>
        <Text font="secondary-body" color="text-03">
          {pdfT("locationUnconfirmed")}
        </Text>
        <Section flexDirection="row" height="fit" gap={2} wrap>
          <Button
            size="sm"
            prominence="secondary"
            disabled={!originalId}
            onClick={() => {
              if (originalId) onShow(issue, originalId, issue.page);
            }}
          >
            {pdfT("showOriginal")}
          </Button>
          <Button
            size="sm"
            prominence="secondary"
            disabled={!revisedId}
            onClick={() => {
              if (revisedId) onShow(issue, revisedId, issue.page);
            }}
          >
            {pdfT("showRevised")}
          </Button>
        </Section>
      </Section>
    </Card>
  );
}
