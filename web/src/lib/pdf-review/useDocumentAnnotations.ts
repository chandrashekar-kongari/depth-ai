"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAnnotationCapability } from "@embedpdf/plugin-annotation/react";
import { LockModeType } from "@embedpdf/plugin-annotation";
import type { PdfAnnotationObject, PdfDocumentObject } from "@embedpdf/models";
import {
  reconcileAnnotations,
  encodeAppearance,
} from "@/lib/pdf-review/embedpdf/adapter";
import { locationKey } from "@/lib/pdf-review/anchors";
import { rectAnchor } from "@/lib/pdf-review/geometry";
import type {
  DrawingEdit,
  LinkedIssue,
  WorkspaceSnapshot,
} from "@/lib/pdf-review/types";

interface DocumentAnnotationsOptions {
  documentId: string;
  document: PdfDocumentObject | undefined;
  snapshot: WorkspaceSnapshot | undefined;
  pending: number;
  enabled: boolean;
  active: boolean;
  tool: string;
  correction: LinkedIssue | null;
  submit: (edit: DrawingEdit) => void;
  onCorrected: () => void;
  retryToken: number;
}

/** The workspace command ledger owns persistence and undo across both PDF columns. */
export function useDocumentAnnotations({
  documentId,
  document,
  snapshot,
  pending,
  enabled,
  active,
  tool,
  correction,
  submit,
  onCorrected,
  retryToken,
}: DocumentAnnotationsOptions) {
  const { provides: capability } = useAnnotationCapability();
  const annotation = useMemo(
    () => capability?.forDocument(documentId) ?? null,
    [capability, documentId]
  );
  const originals = useRef(new Map<string, PdfAnnotationObject>());
  const managed = useRef(new Set<string>());
  const loaded = useRef(false);
  const suppress = useRef(false);
  const discarded = useRef(new Set<string>());
  const applied = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const correctionRef = useRef(correction);
  useEffect(() => {
    correctionRef.current = correction;
  }, [correction]);
  const correctedRef = useRef(onCorrected);
  useEffect(() => {
    correctedRef.current = onCorrected;
  }, [onCorrected]);
  const retry = useCallback(() => {
    applied.current = null;
    setAttempt((previous) => previous + 1);
  }, []);
  const previousRetry = useRef(retryToken);
  useEffect(() => {
    if (previousRetry.current !== retryToken) {
      previousRetry.current = retryToken;
      retry();
    }
  }, [retryToken, retry]);

  useEffect(() => {
    if (
      !annotation ||
      !document ||
      pending ||
      (loaded.current && applied.current === (snapshot?.version ?? -1))
    )
      return;
    let alive = true;
    if (!loaded.current) {
      annotation.setLocked({ type: LockModeType.All });
      setReady(false);
    }
    setError(false);
    reconcileAnnotations(
      annotation,
      snapshot?.state.annotations[documentId] ?? {},
      originals.current,
      managed.current,
      loaded.current ? [] : document.pages.map((page) => page.index),
      (mutation) => {
        suppress.current = true;
        try {
          mutation();
        } finally {
          suppress.current = false;
        }
      }
    )
      .then(() => {
        if (!alive) return;
        loaded.current = true;
        applied.current = snapshot?.version ?? -1;
        setReady(true);
      })
      .catch(() => {
        if (alive) {
          setError(true);
          setReady(false);
        }
      })
      .finally(() => {
        if (alive) suppress.current = false;
      });
    return () => {
      alive = false;
    };
  }, [annotation, document, documentId, snapshot, pending, attempt]);

  useEffect(() => {
    annotation?.setLocked({
      type: ready && enabled && !error ? LockModeType.None : LockModeType.All,
    });
    annotation?.setActiveTool(
      ready && enabled && !error && active && tool !== "select" ? tool : null
    );
  }, [annotation, ready, enabled, error, active, tool]);

  useEffect(() => {
    if (!annotation || !snapshot || !document) return;
    return annotation.onAnnotationEvent((event) => {
      if (
        suppress.current ||
        (event.type !== "create" &&
          event.type !== "update" &&
          event.type !== "delete")
      )
        return;
      if (event.committed) return;
      // Update events carry the old object; read the SDK's already-patched state.
      const object =
        event.type === "update"
          ? annotation.getAnnotationById(event.annotation.id)?.object
          : event.annotation;
      if (!object) {
        setError(true);
        setReady(false);
        return;
      }
      if (discarded.current.has(object.id)) return;
      managed.current.add(object.id);
      const correcting = event.type === "create" ? correctionRef.current : null;
      if (correcting) {
        const page = document.pages[event.pageIndex];
        if (!page) return;
        const anchor = rectAnchor(object.rect, page.size, event.pageIndex + 1);
        if (!anchor) return;
        submit({
          action: "set_anchor",
          document_id: documentId,
          issue_id: locationKey(correcting),
          anchor,
        });
        discarded.current.add(object.id);
        annotation.deleteAnnotation(event.pageIndex, object.id);
        annotation.setActiveTool(null);
        correctionRef.current = null;
        correctedRef.current();
        return;
      }
      if (event.type === "delete") {
        submit({
          action: "delete_annotation",
          document_id: documentId,
          annotation_id: object.id,
          annotation: object,
        });
      } else if (object.type === 13) {
        void annotation
          .exportAnnotations({ pageIndex: event.pageIndex })
          .toPromise()
          .then((items) => {
            const item = items.find((item) => item.annotation.id === object.id);
            const appearance =
              item?.ctx &&
              "data" in item.ctx &&
              item.ctx.data instanceof ArrayBuffer
                ? encodeAppearance(item.ctx.data)
                : null;
            submit({
              action: "upsert_annotation",
              document_id: documentId,
              annotation: object,
              appearance,
            });
          })
          .catch(() => setError(true));
      } else {
        submit({
          action: "upsert_annotation",
          document_id: documentId,
          annotation: object,
        });
      }
    });
  }, [annotation, snapshot, document, documentId, submit]);

  return {
    annotation,
    ready,
    error,
    retry,
  };
}
