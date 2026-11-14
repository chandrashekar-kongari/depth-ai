"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, InputTypeIn, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgChevronDown,
  SvgChevronUp,
  SvgCheckCircle,
  SvgAlertCircle,
} from "@opal/icons";
import type { LinkedIssue, ReviewFocusRequest } from "@/lib/pdf-review/types";
import { PdfReviewWorkspace } from "@/lib/pdf-review/PdfReviewWorkspace";
import type {
  CommentReviewDelta,
  CommentVerdict,
  DrawingComment,
  DrawingExtraIssue,
} from "@/app/app/services/streamingModels";
import { useDrawingReviewLayout } from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";
import {
  DrawingChangesView,
  drawingChangeIssues,
  isVisibleDrawingChange,
} from "@/app/app/message/messageComponents/renderers/DrawingChangesView";

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
              const isVisionComment = comment.id.startsWith("vision-comment-");
              if (review.commented_sheet_file_id)
                anchors[review.commented_sheet_file_id] = {
                  page: comment.page,
                  box: comment.box,
                  pageLevel: comment.page_level,
                  quality:
                    isVisionComment && comment.box
                      ? "located_comment"
                      : undefined,
                };
              if (review.revised_sheet_file_id)
                anchors[review.revised_sheet_file_id] = {
                  page: comment.revised_page ?? comment.page,
                  box: comment.revised_box,
                  pageLevel: comment.revised_page_level,
                  quality: comment.revised_location_verified
                    ? "located_text"
                    : undefined,
                };
              return {
                id: comment.id,
                showMarkerBeforeSelection: isVisionComment,
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
                verdict: issue.kind === "change" ? undefined : "open",
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
            ...drawingChangeIssues(review),
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
  const changeT = useTranslations("chat.messages.drawingChanges");
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

  const ui = useTranslations("chat.workspace");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const comments = review.comments ?? [];
  const extra = review.extra_issues ?? [];
  const search = query.trim().toLocaleLowerCase();
  const matches = (text: string) => text.toLocaleLowerCase().includes(search);
  const attention =
    comments.filter(
      (item) => item.verdict === "open" || item.verdict === "solved_incorrect"
    ).length + extra.filter((item) => item.kind !== "change").length;
  const unclear = comments.filter((item) => item.verdict === "unclear").length;
  const addressed = comments.filter(
    (item) => item.verdict === "solved_correct"
  ).length;
  const filtered = comments.filter(
    (item) =>
      (filter === "all" ||
        (filter === "attention" &&
          (item.verdict === "open" || item.verdict === "solved_incorrect")) ||
        (filter === "unclear" && item.verdict === "unclear") ||
        (filter === "addressed" && item.verdict === "solved_correct")) &&
      matches(
        [item.text, item.request, item.evidence, item.remaining].join(" ")
      )
  );
  const filteredExtra =
    filter === "all" || filter === "attention"
      ? extra.filter(
          (item) =>
            (filter === "all" || item.kind !== "change") &&
            matches(item.title + " " + item.detail)
        )
      : [];

  return (
    <Section
      flexDirection="column"
      alignItems="stretch"
      justifyContent="start"
      gap={3}
      width="full"
      className="depth-review-queue"
    >
      <Section
        flexDirection="row"
        justifyContent="between"
        height="fit"
        gap={2}
      >
        <Text font="main-ui-action" color="text-05">
          {ui("reviewSummary")}
        </Text>
        <Text font="secondary-body" color="text-03">
          {pdfT("reviewCoverage", {
            total: comments.length + extra.length,
            unclear,
          })}
        </Text>
      </Section>
      <Section
        flexDirection="row"
        justifyContent="start"
        wrap
        height="fit"
        gap={1}
      >
        {(
          [
            ["all", comments.length + extra.length],
            ["attention", attention],
            ["unclear", unclear],
            ["addressed", addressed],
          ] as const
        ).map(([value, count]) => (
          <Button
            key={value}
            size="sm"
            prominence={filter === value ? "secondary" : "tertiary"}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {ui(value, { count })}
          </Button>
        ))}
      </Section>
      <InputTypeIn
        searchIcon
        value={query}
        aria-label={ui("searchFindings")}
        placeholder={ui("searchFindings")}
        onChange={(event) => setQuery(event.target.value)}
      />
      {filtered.length === 0 && filteredExtra.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {comments.length === 0 && extra.length === 0
            ? t("noComments.text")
            : ui("noMatchingFindings")}
        </Text>
      ) : null}
      {review.coverage_notices?.map((notice) => (
        <Text key={notice} font="secondary-body" color="text-04">
          {notice}
        </Text>
      ))}
      {filtered.map((comment) => {
        const number = comments.indexOf(comment) + 1;
        const titleSource = /^\s*[+-]?\d+(?:\.\d+)?\s*$/.test(comment.text)
          ? comment.request
          : comment.text;
        const title =
          comment.evidence.trim() ||
          titleSource.split(/\n|Required change:/i)[0]?.trim() ||
          comment.text;
        const open = expanded[comment.id] ?? false;
        return (
          <Card
            key={comment.id}
            border="solid"
            padding={3}
            rounding={2}
            color={
              selectedId === comment.id ? "background-tint-01" : "transparent"
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
              alignItems="stretch"
              justifyContent="start"
              gap={2}
            >
              <Section
                flexDirection="row"
                height="fit"
                justifyContent="between"
                gap={2}
              >
                <Text font="secondary-body" color="text-03">
                  {pdfT("findingNumber", { number })}
                </Text>
                <Tag
                  size="md"
                  icon={
                    comment.verdict === "solved_correct"
                      ? SvgCheckCircle
                      : SvgAlertCircle
                  }
                  color={
                    comment.verdict === "solved_correct"
                      ? "green"
                      : comment.verdict === "unclear"
                        ? "amber"
                        : "red"
                  }
                  title={
                    comment.verdict !== "solved_correct" &&
                    comment.checks?.some(
                      (check) => check.verdict === "solved_correct"
                    )
                      ? t("partiallySolved")
                      : verdictLabel(comment.verdict, t)
                  }
                />
              </Section>
              <Section
                flexDirection="row"
                height="fit"
                justifyContent="between"
                gap={2}
              >
                <Text
                  font="main-ui-action"
                  color="text-05"
                  wordWrap="wrap-anywhere"
                >
                  {title}
                </Text>
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={open ? SvgChevronUp : SvgChevronDown}
                  aria-label={ui("findingDetails", { number })}
                  aria-expanded={open}
                  onClick={() => {
                    selectComment(comment);
                    setExpanded((previous) => ({
                      ...previous,
                      [comment.id]: !open,
                    }));
                  }}
                />
              </Section>
              {comment.remaining && comment.remaining !== title ? (
                <Text
                  font="secondary-body"
                  color="text-04"
                  wordWrap="wrap-anywhere"
                >
                  {comment.remaining}
                </Text>
              ) : null}
              <Section
                flexDirection="row"
                justifyContent="start"
                height="fit"
                gap={1}
                wrap
              >
                <Button
                  size="sm"
                  prominence="tertiary"
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
                  prominence="tertiary"
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
              {open ? (
                <Section
                  height="fit"
                  alignItems="stretch"
                  justifyContent="start"
                  gap={2}
                  padding={2}
                  className="border-t border-border-01"
                >
                  <Text
                    font="secondary-body"
                    color="text-04"
                    wordWrap="wrap-anywhere"
                  >
                    {t("request.text", { request: comment.request })}
                  </Text>
                  {review.drawing_changes?.changes
                    .filter(
                      (change) =>
                        isVisibleDrawingChange(change) &&
                        change.verified_comment_ids?.includes(comment.id)
                    )
                    .map((change) => (
                      <Text
                        key={change.id}
                        font="secondary-body"
                        color="text-03"
                      >
                        {change.vision_explanation ||
                          changeT(change.kind, {
                            before: change.before_text,
                            after: change.after_text,
                          })}
                      </Text>
                    ))}
                  {comment.checks?.map((check) => (
                    <Text
                      key={check.label}
                      font="secondary-body"
                      color="text-04"
                    >
                      {t("requirementCheck", {
                        label: check.label,
                        status: verdictLabel(check.verdict, t),
                        evidence: check.evidence,
                      })}
                    </Text>
                  ))}
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
                  {title !== comment.text ? (
                    <Text
                      font="secondary-body"
                      color="text-03"
                      wordWrap="wrap-anywhere"
                    >
                      {comment.text}
                    </Text>
                  ) : null}
                </Section>
              ) : null}
            </Section>
          </Card>
        );
      })}
      {filteredExtra.length > 0 ? (
        <Text font="secondary-body" color="text-04">
          {t("otherFindings")}
        </Text>
      ) : null}
      {filteredExtra.map((issue) => (
        <ExtraIssueRow
          key={issue.id}
          issue={issue}
          number={comments.length + extra.indexOf(issue) + 1}
          originalId={review.commented_sheet_file_id}
          revisedId={review.revised_sheet_file_id}
          onShow={onShow}
        />
      ))}
      {review.vision_model ? (
        <details className="depth-review-details">
          <summary>
            <Text as="span" font="secondary-body" color="text-03">
              {ui("reviewDetails")}
            </Text>
          </summary>
          <Text font="secondary-body" color="text-03">
            {pdfT("visionModel", { model: review.vision_model })}
          </Text>
        </details>
      ) : null}
      {review.drawing_changes ? (
        <DrawingChangesView review={review} onShow={onShow} />
      ) : null}
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
    <Card border="solid" padding={3} rounding={2} color="transparent">
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
        <Text font="secondary-body" color="text-04">
          {issue.title}
        </Text>
        {issue.kind === "change" ? (
          <Text font="secondary-body" color="text-03">
            {t("unrequestedChange")}
          </Text>
        ) : null}
        <Text font="secondary-body" color="text-03">
          {t("issueDetail.text", { detail: issue.detail, page: issue.page })}
        </Text>
        {issue.before_evidence && issue.after_evidence ? (
          <Text font="secondary-body" color="text-03">
            {t("changeEvidence", {
              before: issue.before_evidence,
              after: issue.after_evidence,
            })}
          </Text>
        ) : null}
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
