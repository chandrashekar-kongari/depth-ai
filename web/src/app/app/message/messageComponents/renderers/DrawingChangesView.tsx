"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type {
  CommentReviewDelta,
  DrawingChange,
} from "@/app/app/services/streamingModels";
import type { LinkedIssue } from "@/lib/pdf-review/types";

export function isVisibleDrawingChange(change: DrawingChange): boolean {
  return change.vision_validation === "confirmed";
}

export function drawingChangeIssues(review: CommentReviewDelta): LinkedIssue[] {
  return (review.drawing_changes?.changes ?? [])
    .filter(
      (change) =>
        isVisibleDrawingChange(change) &&
        !change.verified_comment_ids?.some((id) =>
          review.comments.some((comment) => comment.id === id)
        )
    )
    .map((change) => {
      const anchors: LinkedIssue["anchors"] = {};
      if (review.commented_sheet_file_id)
        anchors[review.commented_sheet_file_id] = {
          page: change.page,
          box: change.original_box,
          pageLevel: !change.original_box,
          quality: "located_difference",
        };
      if (review.revised_sheet_file_id)
        anchors[review.revised_sheet_file_id] = {
          page: change.revised_page ?? change.page,
          box: change.revised_box,
          pageLevel: !change.revised_box,
          quality: "located_difference",
        };
      return {
        id: change.id,
        title:
          change.vision_explanation ||
          [change.before_text, change.after_text].filter(Boolean).join(" → "),
        request: "",
        evidence: [change.before_text, change.after_text]
          .filter(Boolean)
          .join(" → "),
        remaining: "",
        anchors,
      };
    });
}

export function DrawingChangesView({
  review,
  onShow,
}: {
  review: CommentReviewDelta;
  onShow: (issue: { id: string }, documentId: string, page: number) => void;
}) {
  const t = useTranslations("chat.messages.drawingChanges");
  const pdfT = useTranslations("chat.messages.pdfWorkspace");
  const [unlinkedOnly, setUnlinkedOnly] = useState(false);
  const [showVisual, setShowVisual] = useState(false);
  const audit = review.drawing_changes;
  if (!audit) return null;
  const commentIds = new Set(review.comments.map((comment) => comment.id));
  const standalone = audit.changes.filter(
    (change) =>
      isVisibleDrawingChange(change) &&
      !change.verified_comment_ids?.some((id) => commentIds.has(id))
  );
  const shown = standalone.filter(
    (change) => !unlinkedOnly || change.possible_comment_ids.length === 0
  );
  const visualCount = shown.filter((change) => change.kind === "visual").length;
  return (
    <Section alignItems="stretch" justifyContent="start" gap={2} height="fit">
      <Text font="heading-h3">
        {t("title", {
          count: standalone.filter((change) => change.kind !== "visual").length,
        })}
      </Text>
      <Text font="secondary-body" color="text-03">
        {t("scope")}
      </Text>
      <Text font="secondary-body" color="text-03">
        {t("status", {
          status: t(audit.status),
          pages: audit.compared_pages.join(", "),
        })}
      </Text>
      <Text font="secondary-body" color="text-03">
        {t("commentCoverage", {
          status: t(review.comment_verification_status ?? "incomplete"),
          pages: review.comment_verified_pages?.join(", ") || "—",
        })}
      </Text>
      <Text font="secondary-body" color="text-03">
        {t("changeCoverage", {
          status: t(audit.validation_status ?? "incomplete"),
          pages: audit.validated_pages?.join(", ") || "—",
        })}
      </Text>
      {Object.entries(audit.page_pairs ?? {}).map(([before, after]) => (
        <Text key={`pair-${before}`} font="secondary-body" color="text-03">
          {t("pagePair", { before, after })}
        </Text>
      ))}
      {Object.entries(audit.skipped_original_pages ?? {}).map(
        ([page, reason]) => (
          <Text key={`before-${page}`} font="secondary-body" color="text-04">
            {t("skippedBefore", { page, reason })}
          </Text>
        )
      )}
      {Object.entries(audit.unmatched_revised_pages ?? {}).map(
        ([page, reason]) => (
          <Text key={`after-${page}`} font="secondary-body" color="text-04">
            {t("unmatchedAfter", { page, reason })}
          </Text>
        )
      )}
      {!audit.changes.some(isVisibleDrawingChange) ? (
        <Text font="secondary-body" color="text-03">
          {t(
            audit.status === "complete" &&
              audit.validation_status === "complete" &&
              review.comment_verification_status === "complete"
              ? "noDifferences"
              : "reviewIncomplete"
          )}
        </Text>
      ) : null}
      {audit.warnings.map((warning, index) => (
        <Text key={index} font="secondary-body" color="text-04">
          {warning}
        </Text>
      ))}
      <Section flexDirection="row" justifyContent="start" gap={1} height="fit">
        <Button
          size="sm"
          prominence={!unlinkedOnly ? "secondary" : "tertiary"}
          aria-pressed={!unlinkedOnly}
          onClick={() => setUnlinkedOnly(false)}
        >
          {t("all")}
        </Button>
        <Button
          size="sm"
          prominence={unlinkedOnly ? "secondary" : "tertiary"}
          aria-pressed={unlinkedOnly}
          onClick={() => setUnlinkedOnly(true)}
        >
          {t("unlinked")}
        </Button>
      </Section>
      {visualCount > 0 ? (
        <Button
          size="sm"
          prominence="tertiary"
          aria-expanded={showVisual}
          onClick={() => setShowVisual(!showVisual)}
        >
          {t("visualGroup", { count: visualCount })}
        </Button>
      ) : null}
      {shown
        .filter((change) => change.kind !== "visual" || showVisual)
        .map((change) => (
          <Card
            key={change.id}
            border="solid"
            padding={3}
            rounding={2}
            color="transparent"
          >
            <Section
              alignItems="stretch"
              justifyContent="start"
              gap={1}
              height="fit"
            >
              <Text font="main-ui-action">
                {change.vision_explanation ||
                  t(change.kind, {
                    before: change.before_text,
                    after: change.after_text,
                  })}
              </Text>
              <Text font="secondary-body" color="text-03">
                {change.verified_comment_ids?.length
                  ? t("verifiedLink", {
                      ids: change.verified_comment_ids.join(", "),
                    })
                  : change.possible_comment_ids.length
                    ? t("possibleLink", {
                        ids: change.possible_comment_ids.join(", "),
                      })
                    : t("noLink")}
              </Text>
              {change.kind !== "visual" && !change.vision_explanation ? (
                <Text font="secondary-body" color="text-03">
                  {t("validation.confirmed")}
                </Text>
              ) : null}
              <Section
                flexDirection="row"
                justifyContent="start"
                gap={1}
                height="fit"
                wrap
              >
                <Button
                  size="sm"
                  prominence="tertiary"
                  disabled={!review.commented_sheet_file_id}
                  onClick={() => {
                    if (review.commented_sheet_file_id)
                      onShow(
                        change,
                        review.commented_sheet_file_id,
                        change.page
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
                        change,
                        review.revised_sheet_file_id,
                        change.revised_page ?? change.page
                      );
                  }}
                >
                  {pdfT("showRevised")}
                </Button>
              </Section>
            </Section>
          </Card>
        ))}
    </Section>
  );
}
