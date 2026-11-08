"use client";

import { isVisibleDrawingChange } from "@/app/app/message/messageComponents/renderers/DrawingChangesView";

import { useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleUpload,
  InputTextArea,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { DrawingReviewLayoutProvider } from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";
import {
  useEngineeringReview,
  useEngineeringReviews,
} from "@/lib/engineering/hooks";
import type { DecisionValue, EngineeringReview } from "@/lib/engineering/types";

const CommentReviewView = dynamic(
  () =>
    import("@/app/app/message/messageComponents/renderers/CommentReviewView").then(
      (module) => module.CommentReviewView
    ),
  { ssr: false }
);

function reviewFileUrl(fileId: string): string {
  const [reviewId, role] = fileId.split("/");
  return `/api/engineering/reviews/${encodeURIComponent(reviewId ?? "")}/files/${encodeURIComponent(role ?? "")}`;
}

function FindingDecision({
  review,
  findingId,
  onSaved,
}: {
  review: EngineeringReview;
  findingId: string;
  onSaved: () => void;
}) {
  const t = useTranslations("engineeringReviews");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const latest = review.decisions
    .filter((decision) => decision.finding_id === findingId)
    .at(-1);
  async function save(value: DecisionValue) {
    setBusy(true);
    setError(false);
    try {
      const response = await fetch(
        `/api/engineering/reviews/${review.id}/findings/${encodeURIComponent(findingId)}/decision`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            value,
            note,
            expected_version: review.version,
          }),
        }
      );
      if (!response.ok) throw new Error();
      onSaved();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Section alignItems="stretch" gap={2}>
      <Text>{findingId}</Text>
      {latest ? <Text>{t(latest.value)}</Text> : null}
      <InputTextArea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder={t("note")}
        maxLength={2000}
      />
      <Section flexDirection="row" gap={2}>
        <Button disabled={busy} onClick={() => void save("accept")}>
          {t("accept")}
        </Button>
        <Button
          disabled={busy}
          prominence="secondary"
          onClick={() => void save("reject")}
        >
          {t("reject")}
        </Button>
        <Button
          disabled={busy}
          prominence="tertiary"
          onClick={() => void save("needs_review")}
        >
          {t("needs_review")}
        </Button>
      </Section>
      {error ? <Text>{t("saveError")}</Text> : null}
    </Section>
  );
}

export default function EngineeringReviewsPage() {
  const t = useTranslations("engineeringReviews");
  const searchParams = useSearchParams();
  const [selected, setSelected] = useState<string | null>(
    searchParams.get("review")
  );
  const [original, setOriginal] = useState<File | null>(null);
  const [revised, setRevised] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const requestKey = useRef<string | null>(null);
  const queue = useEngineeringReviews();
  const detail = useEngineeringReview(selected);
  const review = detail.data;

  function select(id: string) {
    setSelected(id);
    window.history.replaceState(
      null,
      "",
      `/app/reviews?review=${encodeURIComponent(id)}`
    );
  }
  async function submit() {
    if (!original || !revised || !confirmed) return;
    setBusy(true);
    setError(false);
    requestKey.current ??= crypto.randomUUID();
    const form = new FormData();
    form.set("original", original);
    form.set("revised", revised);
    form.set("page_order_confirmed", "true");
    form.set("request_key", requestKey.current);
    try {
      const response = await fetch("/api/engineering/reviews", {
        method: "POST",
        body: form,
      });
      if (!response.ok) throw new Error();
      const created: EngineeringReview = await response.json();
      select(created.id);
      requestKey.current = null;
      void queue.mutate();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!review) return;
    setError(false);
    try {
      const response = await fetch(
        `/api/engineering/reviews/${review.id}/cancel`,
        { method: "POST" }
      );
      if (!response.ok) throw new Error();
      void detail.mutate();
      void queue.mutate();
    } catch {
      setError(true);
    }
  }
  return (
    <Section
      alignItems="stretch"
      justifyContent="start"
      padding={6}
      gap={4}
      height="full"
      className="overflow-y-auto"
    >
      <Text font="heading-h2">{t("title")}</Text>
      <Text>{t("scope")}</Text>
      <Text>{t("original")}</Text>
      <InputSingleUpload
        mode="file"
        value={original}
        onFileChange={(file) => {
          setOriginal(file);
          setConfirmed(false);
          requestKey.current = null;
        }}
        accept=".pdf"
        maxSizeKb={20480}
        placeholder={t("original")}
      />
      <Text>{t("revised")}</Text>
      <InputSingleUpload
        mode="file"
        value={revised}
        onFileChange={(file) => {
          setRevised(file);
          setConfirmed(false);
          requestKey.current = null;
        }}
        accept=".pdf"
        maxSizeKb={20480}
        placeholder={t("revised")}
      />
      <Button
        prominence="secondary"
        aria-pressed={confirmed}
        onClick={() => setConfirmed(!confirmed)}
      >
        {t(confirmed ? "confirmed" : "confirm")}
      </Button>
      <Button
        disabled={busy || !original || !revised || !confirmed}
        onClick={() => void submit()}
      >
        {t("submit")}
      </Button>
      {error || queue.error || detail.error ? <Text>{t("error")}</Text> : null}
      {queue.isLoading ? <Text>{t("loading")}</Text> : null}
      {queue.data?.map((item) => (
        <Button
          key={item.id}
          prominence="tertiary"
          aria-pressed={selected === item.id}
          onClick={() => select(item.id)}
        >{`${item.original_name} → ${item.revised_name} · ${t(item.status)}`}</Button>
      ))}
      {review ? (
        <Section alignItems="stretch" gap={4}>
          <Text>{t(review.status)}</Text>
          {review.status === "queued" || review.status === "running" ? (
            <Button prominence="secondary" onClick={() => void cancel()}>
              {t("cancel")}
            </Button>
          ) : null}
          {review.error ? <Text>{review.error}</Text> : null}
          <Button
            href={`/api/engineering/reviews/${review.id}/export`}
            prominence="secondary"
          >
            {t("export")}
          </Button>
          {review.result ? (
            <DrawingReviewLayoutProvider
              active
              mode="comments"
              reviewKey={review.id}
            >
              <Text>{review.result.status}</Text>
              <CommentReviewView
                review={{ ...review.result, type: "comment_review_delta" }}
                fileUrl={reviewFileUrl}
              />
              <Text>{t("decisions")}</Text>
              {[
                ...review.result.comments,
                ...review.result.extra_issues,
                ...(review.result.drawing_changes?.changes ?? []).filter(
                  isVisibleDrawingChange
                ),
              ].map((finding) => (
                <FindingDecision
                  key={finding.id}
                  review={review}
                  findingId={finding.id}
                  onSaved={() => void detail.mutate()}
                />
              ))}
            </DrawingReviewLayoutProvider>
          ) : null}
        </Section>
      ) : null}
    </Section>
  );
}
