"use client";

/* oxlint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- The application surface provides keyboard camera controls. */

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useAnnotation } from "@embedpdf/plugin-annotation/react";
import { useExportCapability } from "@embedpdf/plugin-export/react";
import { usePrintCapability } from "@embedpdf/plugin-print/react";
import { AnnotationLayer } from "@embedpdf/plugin-annotation/react";
import { PagePointerProvider } from "@embedpdf/plugin-interaction-manager/react";
import { SelectionLayer } from "@embedpdf/plugin-selection/react";
import { useDocumentAnnotations } from "@/lib/pdf-review/useDocumentAnnotations";
import { useDocumentState } from "@embedpdf/core/react";
import { useDocumentManagerCapability } from "@embedpdf/plugin-document-manager/react";
import { useRenderCapability } from "@embedpdf/plugin-render/react";
import { PdfErrorCode, type Rect, type Size } from "@embedpdf/models";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";

import { cn } from "@opal/utils";
import {
  canvasTarget,
  centerCamera,
  fitCamera,
  frameVisible,
  pageFrame,
  zoomCamera,
  PAGE_WIDTH,
  COLUMN_GAP,
  type CanvasCamera,
} from "@/lib/pdf-review/camera";
import { issueFocusTarget } from "@/lib/pdf-review/navigation";
import { useDrawingWorkspace } from "@/lib/pdf-review/hooks";
import { useTextLocations } from "@/lib/pdf-review/useTextLocations";
import { ReviewStatusMarkers } from "@/lib/pdf-review/ReviewStatusMarkers";
import type {
  PdfReviewWorkspaceProps,
  ReviewDocument,
  ReviewFocusRequest,
  WorkspaceSnapshot,
  LinkedIssue,
} from "@/lib/pdf-review/types";
import styles from "@/lib/pdf-review/canvas.module.css";
import { CanvasDock } from "@/lib/pdf-review/CanvasDock";
import attention from "@/lib/pdf-review/attention.module.css";
import { scheduleAttentionEnd } from "@/lib/pdf-review/AttentionRing";

type PdfCanvasProps = PdfReviewWorkspaceProps;

export function PdfCanvas({
  documents,
  issues = [],
  focusRequest,
  selectedIssueId,
  onIssueSelect,
  pageNumber,
  onPageChange,
  fill,
}: PdfCanvasProps) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const ui = useTranslations("chat.workspace");
  const root = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  const cameraSize = useMemo(
    () => ({ ...size, height: Math.max(0, size.height - 88) }),
    [size]
  );
  const [camera, setCamera] = useState<CanvasCamera>({
    x: 32,
    y: 64,
    scale: 0.5,
  });
  const [geometry, setGeometry] = useState<Record<string, Size[]>>({});
  const [activeId, setActiveId] = useState(documents[0]?.id ?? "");
  const [editing, setEditing] = useState(false);
  const [tool, setTool] = useState("select");
  const [correctionId, setCorrectionId] = useState<string | null>(null);
  const [annotationStatus, setAnnotationStatus] = useState<
    Record<string, { ready: boolean; error: boolean }>
  >({});
  const [annotationRetry, setAnnotationRetry] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportFailed, setExportFailed] = useState(false);
  const { provides: annotation, state: annotationState } =
    useAnnotation(activeId);
  const { provides: exporter } = useExportCapability();
  const { provides: printer } = usePrintCapability();
  const [pan, setPan] = useState(false);
  const [space, setSpace] = useState(false);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ id: number; x: number; y: number } | null>(null);
  const [localFocus, setLocalFocus] = useState<ReviewFocusRequest | null>(null);
  const request = localFocus ?? focusRequest;
  const cancelled = useRef<string | null>(null);
  const initialFit = useRef(false);
  const { provides: manager } = useDocumentManagerCapability();
  const workspace = useDrawingWorkspace(
    documents.map((document) => document.id)
  );
  const { snapshot, submit, pending, failed, openError } = workspace;
  const editable =
    !!snapshot &&
    !!annotationStatus[activeId]?.ready &&
    !annotationStatus[activeId]?.error &&
    !failed &&
    !openError &&
    !exporting;
  const selected = annotationState.selectedUid
    ? (annotationState.byUid[annotationState.selectedUid]?.object ?? null)
    : null;
  const reportAnnotationState = useCallback(
    (id: string, ready: boolean, error: boolean) => {
      setAnnotationStatus((previous) =>
        previous[id]?.ready === ready && previous[id]?.error === error
          ? previous
          : { ...previous, [id]: { ready, error } }
      );
    },
    []
  );
  const corrected = useCallback(() => {
    setCorrectionId(null);
    setTool("select");
  }, []);
  function chooseTool(next: string) {
    setCorrectionId(null);
    setPan(false);
    setEditing(true);
    setTool(next);
    annotation?.setActiveTool(next === "select" ? null : next);
  }
  function activateDocument(documentId: string, page: number) {
    if (documentId !== activeId) {
      annotation?.setActiveTool(null);
      annotation?.deselectAnnotation();
    }
    setActiveId(documentId);
    manager?.setActiveDocument(documentId);
    onPageChange(page);
  }
  async function download() {
    const descriptor = documents.find((document) => document.id === activeId);
    if (!annotation || !exporter || !descriptor || !editable || pending) return;
    setExporting(true);
    setExportFailed(false);
    try {
      await annotation.commit().toPromise();
      const bytes = await exporter
        .forDocument(activeId)
        .saveAsCopy()
        .toPromise();
      const url = URL.createObjectURL(
        new Blob([bytes], { type: "application/pdf" })
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = descriptor.filename.replace(/\.pdf$/i, "-reviewed.pdf");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setExportFailed(true);
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    setLocalFocus(null);
    setEditing(false);
  }, [focusRequest]);
  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const reportGeometry = useCallback((id: string, pages: Size[]) => {
    setGeometry((previous) =>
      JSON.stringify(previous[id]) === JSON.stringify(pages)
        ? previous
        : { ...previous, [id]: pages }
    );
  }, []);
  const fitAll = useCallback(() => {
    const frames = documents.flatMap((document, column) => {
      const pages = geometry[document.id];
      return pages?.length ? [pageFrame(pages, column, 0)] : [];
    });
    if (!frames.length || size.width <= 0 || size.height <= 0) return;
    setCamera(
      fitCamera(cameraSize, {
        origin: { x: 0, y: 0 },
        size: {
          width: documents.length * (PAGE_WIDTH + COLUMN_GAP) - COLUMN_GAP,
          height: Math.max(...frames.map((frame) => frame.size.height)) + 48,
        },
      })
    );
  }, [documents, geometry, size, cameraSize]);
  useEffect(() => {
    if (
      initialFit.current ||
      !size.width ||
      !size.height ||
      !documents.every((document) => geometry[document.id]?.length)
    )
      return;
    initialFit.current = true;
    fitAll();
  }, [documents, geometry, size, fitAll]);

  function cancelFocus() {
    cancelled.current = request?.id ?? null;
  }
  const focus = useCallback(
    (next: ReviewFocusRequest, target: Rect): boolean => {
      if (size.width <= 0 || size.height <= 0 || cancelled.current === next.id)
        return false;
      initialFit.current = true;
      setCamera((previous) => centerCamera(previous, cameraSize, target));
      setActiveId(next.documentId);
      manager?.setActiveDocument(next.documentId);
      onPageChange(next.page);
      return true;
    },
    [size, cameraSize, manager, onPageChange]
  );

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    function wheel(event: WheelEvent) {
      event.preventDefault();
      cancelled.current = request?.id ?? null;
      const bounds = element?.getBoundingClientRect();
      if (!bounds) return;
      const multiplier =
        event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? size.height : 1;
      if (event.ctrlKey || event.metaKey) {
        setCamera((previous) =>
          zoomCamera(
            previous,
            previous.scale * Math.exp(-event.deltaY * multiplier * 0.005),
            { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
          )
        );
      } else {
        setCamera((previous) => ({
          ...previous,
          x:
            previous.x -
            (event.shiftKey ? event.deltaY : event.deltaX) * multiplier,
          y: previous.y - (event.shiftKey ? 0 : event.deltaY) * multiplier,
        }));
      }
    }
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [request?.id, size.height]);

  function navigate(documentId: string, page: number) {
    const pages = geometry[documentId];
    const column = documents.findIndex(
      (document) => document.id === documentId
    );
    if (!pages?.length || column < 0) return;
    cancelFocus();
    const next = Math.max(1, Math.min(page, pages.length));
    setCamera((previous) =>
      centerCamera(previous, cameraSize, pageFrame(pages, column, next - 1))
    );
    setActiveId(documentId);
    manager?.setActiveDocument(documentId);
    onPageChange(next);
  }
  function zoom(factor: number) {
    cancelFocus();
    setCamera((previous) =>
      zoomCamera(previous, previous.scale * factor, {
        x: cameraSize.width / 2,
        y: cameraSize.height / 2,
      })
    );
  }
  const total = geometry[activeId]?.length ?? 1;
  return (
    <Section
      ref={root}
      height={fill ? "full" : undefined}
      alignItems="stretch"
      justifyContent="start"
      gap={0}
      className="min-h-0 overflow-hidden"
    >
      <Section
        height={fill ? "full" : undefined}
        alignItems="stretch"
        justifyContent="start"
        gap={0}
        className={cn("relative min-h-0 flex-1", styles.shell)}
      >
        <div
          ref={viewport}
          data-pdf-canvas
          role="application"
          tabIndex={0}
          aria-label={ui("workspace")}
          className={cn(
            styles.viewport,
            "min-h-0 w-full",
            fill ? "flex-1" : "h-[65vh]"
          )}
          style={{
            cursor: dragging ? "grabbing" : pan || space ? "grab" : "default",
          }}
          onKeyDown={(event) => {
            if (
              event.target instanceof HTMLElement &&
              event.target.closest(
                "button,input,textarea,[contenteditable=true]"
              )
            )
              return;
            if (event.code === "Space") {
              event.preventDefault();
              setSpace(true);
            }
            if (event.key === "Escape") {
              setPan(false);
              setSpace(false);
              setEditing(false);
              setCorrectionId(null);
              setTool("select");
              annotation?.setActiveTool(null);
              annotation?.deselectAnnotation();
            }
            if (event.key === "+" || event.key === "=") {
              event.preventDefault();
              zoom(1.2);
            }
            if (event.key === "-") {
              event.preventDefault();
              zoom(1 / 1.2);
            }
            if (
              (event.ctrlKey || event.metaKey) &&
              ["z", "y"].includes(event.key.toLowerCase())
            ) {
              event.preventDefault();
              if (editable && !pending) {
                const redo = event.shiftKey || event.key.toLowerCase() === "y";
                if (redo ? snapshot?.can_redo : snapshot?.can_undo)
                  submit({ action: redo ? "redo" : "undo" });
              }
            }
            if (
              (event.key === "Delete" || event.key === "Backspace") &&
              editing &&
              selected &&
              editable
            ) {
              event.preventDefault();
              annotation?.deleteAnnotation(selected.pageIndex, selected.id);
            }
            if (event.key === "0") {
              event.preventDefault();
              cancelFocus();
              fitAll();
            }
          }}
          onKeyUp={(event) => {
            if (event.code === "Space") {
              event.preventDefault();
              setSpace(false);
            }
          }}
          onBlur={() => {
            setSpace(false);
            drag.current = null;
            setDragging(false);
          }}
          onPointerDown={(event) => {
            if (
              event.target instanceof HTMLElement &&
              event.target.closest("button,input")
            )
              return;
            if (
              !(
                pan ||
                space ||
                event.button === 1 ||
                (event.pointerType === "touch" && !editing) ||
                (event.target instanceof HTMLElement &&
                  !event.target.closest(
                    "[data-pdf-document],[data-pdf-annotation-page]"
                  ))
              )
            )
              return;
            event.preventDefault();
            cancelFocus();
            viewport.current?.focus();
            drag.current = {
              id: event.pointerId,
              x: event.clientX,
              y: event.clientY,
            };
            event.currentTarget.setPointerCapture(event.pointerId);
            setDragging(true);
          }}
          onPointerMove={(event) => {
            const start = drag.current;
            if (!start || start.id !== event.pointerId) return;
            const dx = event.clientX - start.x,
              dy = event.clientY - start.y;
            drag.current = { id: start.id, x: event.clientX, y: event.clientY };
            setCamera((previous) => ({
              ...previous,
              x: previous.x + dx,
              y: previous.y + dy,
            }));
          }}
          onPointerUp={(event) => {
            if (drag.current?.id === event.pointerId) {
              drag.current = null;
              setDragging(false);
            }
          }}
          onPointerCancel={() => {
            drag.current = null;
            setDragging(false);
          }}
          onLostPointerCapture={() => {
            drag.current = null;
            setDragging(false);
          }}
        >
          <div
            className={styles.surface}
            style={{
              transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})`,
              pointerEvents: pan || space ? "none" : undefined,
            }}
          >
            {documents.map((document, column) => (
              <CanvasDocument
                key={document.id}
                document={document}
                column={column}
                camera={camera}
                viewport={size}
                snapshot={snapshot}
                workspace={workspace}
                active={activeId === document.id}
                editing={editing}
                tool={tool}
                pan={pan || space}
                correctionId={correctionId}
                overlayContainer={viewport.current}
                onActivate={activateDocument}
                onAnnotationState={reportAnnotationState}
                onCorrected={corrected}
                retryToken={annotationRetry}
                issues={issues}
                selectedIssueId={selectedIssueId}
                request={request}
                onGeometry={reportGeometry}
                onFocus={focus}
                onSelect={(issueId, page) => {
                  onIssueSelect?.(issueId, page);
                  setLocalFocus({
                    id: crypto.randomUUID(),
                    issueId,
                    page,
                    documentId: document.id,
                  });
                }}
              />
            ))}
          </div>
        </div>
        <CanvasDock
          documents={documents}
          activeId={activeId}
          page={pageNumber}
          total={total}
          scale={camera.scale}
          pan={pan}
          onPanChange={(next) => {
            setPan(next);
            if (!next) setEditing(true);
            setCorrectionId(null);
            setTool("select");
            annotation?.setActiveTool(null);
          }}
          editing={editing}
          tool={tool}
          editable={editable}
          pending={pending}
          canUndo={!!snapshot?.can_undo}
          canRedo={!!snapshot?.can_redo}
          selected={selected}
          onToolChange={chooseTool}
          onUndo={() => submit({ action: "undo" })}
          onRedo={() => submit({ action: "redo" })}
          onDelete={() => {
            if (selected)
              annotation?.deleteAnnotation(selected.pageIndex, selected.id);
          }}
          onNoteChange={(contents) => {
            if (selected)
              annotation?.updateAnnotation(selected.pageIndex, selected.id, {
                contents,
              });
          }}
          onExport={() => void download()}
          onPrint={() => {
            void printer
              ?.forDocument(activeId)
              .print()
              .toPromise()
              .catch(() => setExportFailed(true));
          }}
          onCorrect={
            selectedIssueId
              ? () => {
                  setCorrectionId(selectedIssueId);
                  setEditing(true);
                  setPan(false);
                  setTool("square");
                  annotation?.setActiveTool("square");
                }
              : undefined
          }
          status={
            exportFailed
              ? t("exportFailed")
              : failed || openError || annotationStatus[activeId]?.error
                ? t("saveFailed")
                : pending
                  ? t("saving")
                  : snapshot
                    ? correctionId
                      ? t("placeAnchor")
                      : t("saved")
                    : t("loading")
          }
          onRetry={() => {
            setAnnotationRetry((previous) => previous + 1);
            if (failed) void workspace.retry();
            else if (openError) void workspace.reopen();
            else void workspace.reload();
          }}
          hasError={
            exportFailed ||
            !!failed ||
            !!openError ||
            !!annotationStatus[activeId]?.error
          }
          onNavigate={navigate}
          onZoom={zoom}
          onFitAll={() => {
            cancelFocus();
            fitAll();
          }}
          onFitPage={() => {
            const pages = geometry[activeId];
            if (pages?.length) {
              cancelFocus();
              setCamera(
                fitCamera(
                  cameraSize,
                  pageFrame(
                    pages,
                    Math.max(
                      0,
                      documents.findIndex(
                        (document) => document.id === activeId
                      )
                    ),
                    Math.min(pageNumber, pages.length) - 1
                  )
                )
              );
            }
          }}
          onAnnotate={() => {
            cancelFocus();
            setEditing(true);
            setPan(false);
          }}
        />
      </Section>
    </Section>
  );
}

interface CanvasDocumentProps {
  document: ReviewDocument;
  column: number;
  camera: CanvasCamera;
  viewport: Size;
  snapshot: WorkspaceSnapshot | undefined;
  issues: LinkedIssue[];
  selectedIssueId?: string | null;
  request?: ReviewFocusRequest | null;
  onGeometry: (id: string, pages: Size[]) => void;
  onFocus: (request: ReviewFocusRequest, target: Rect) => boolean;
  onSelect: (id: string, page: number) => void;
  workspace: ReturnType<typeof useDrawingWorkspace>;
  active: boolean;
  editing: boolean;
  tool: string;
  pan: boolean;
  correctionId: string | null;
  overlayContainer: HTMLElement | null;
  onActivate: (id: string, page: number) => void;
  onAnnotationState: (id: string, ready: boolean, error: boolean) => void;
  onCorrected: () => void;
  retryToken: number;
}

function CanvasDocument({
  document,
  column,
  camera,
  viewport,
  snapshot,
  issues,
  selectedIssueId,
  request,
  onGeometry,
  onFocus,
  onSelect,
  workspace,
  active,
  editing,
  tool,
  pan,
  correctionId,
  overlayContainer,
  onActivate,
  onAnnotationState,
  onCorrected,
  retryToken,
}: CanvasDocumentProps) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const state = useDocumentState(document.id);
  const pdf = state?.document;
  const locations = useTextLocations(
    snapshot,
    document.id,
    issues,
    document.role
  );
  const controller = useDocumentAnnotations({
    documentId: document.id,
    document: pdf ?? undefined,
    snapshot,
    pending: workspace.pending,
    enabled: editing && !!snapshot && !workspace.failed && !workspace.openError,
    active,
    tool,
    correction: active
      ? (locations.issues.find((issue) => issue.id === correctionId) ?? null)
      : null,
    submit: workspace.submit,
    onCorrected,
    retryToken,
  });
  useEffect(() => {
    onAnnotationState(document.id, controller.ready, controller.error);
  }, [document.id, controller.ready, controller.error, onAnnotationState]);
  const signature = JSON.stringify(locations.issues);
  const handled = useRef<string | null>(null);
  const [ring, setRing] = useState<{
    requestId: string;
    page: number;
    target: Rect;
  } | null>(null);
  useEffect(() => {
    if (pdf)
      onGeometry(
        document.id,
        pdf.pages.map((page) => page.size)
      );
  }, [pdf, document.id, onGeometry]);
  useEffect(() => {
    if (
      !pdf ||
      !request ||
      request.documentId !== document.id ||
      handled.current === request.id ||
      !viewport.width ||
      !viewport.height
    )
      return;
    const target = issueFocusTarget(request, locations.issues, pdf, snapshot);
    const size = pdf.pages[target.page - 1]?.size;
    if (!size) return;
    const frame = pageFrame(
      pdf.pages.map((page) => page.size),
      column,
      target.page - 1
    );
    const region = canvasTarget(frame, size, target.rect);
    if (!onFocus({ ...request, page: target.page }, region)) return;
    if (!locations.isLoading) handled.current = request.id;
    setRing(
      target.rect
        ? { requestId: request.id, page: target.page, target: region }
        : null
    );
  }, [
    pdf,
    request,
    document.id,
    column,
    snapshot,
    signature,
    locations.isLoading,
    onFocus,
    viewport.width,
    viewport.height,
  ]);
  useEffect(() => {
    if (!ring) return;
    return scheduleAttentionEnd(() => setRing(null));
  }, [ring]);
  if (!pdf)
    return (
      <div
        style={{
          position: "absolute",
          left: column * (PAGE_WIDTH + COLUMN_GAP),
          top: 48,
        }}
      >
        <Section padding={4} width={PAGE_WIDTH} height="fit">
          <Text font="secondary-body" color="text-03">
            {t(state?.status === "error" ? "loadFailed" : "loading")}
          </Text>
        </Section>
      </div>
    );
  const pages = pdf.pages.map((page) => page.size);
  return (
    <>
      {pages.map((size, index) => {
        const frame = pageFrame(pages, column, index);
        const visible = frameVisible(camera, viewport, frame);
        return (
          <Fragment key={index}>
            <div
              className={styles.page}
              data-pdf-document={document.id}
              data-pdf-page={index + 1}
              style={{
                left: frame.origin.x,
                top: frame.origin.y,
                width: frame.size.width,
                height: frame.size.height,
              }}
            >
              <div
                className={styles.label}
                style={{
                  top: -32 / camera.scale,
                  transform: `scale(${1 / camera.scale})`,
                  transformOrigin: "top left",
                }}
              >
                <Section flexDirection="row" width="fit" height="fit" gap={1}>
                  <Text font="secondary-action" color="text-05">
                    {document.label}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {t("evidencePage", { page: index + 1 })}
                  </Text>
                </Section>
              </div>
              {visible ? (
                <>
                  <CanvasPageImage
                    key={snapshot?.version}
                    documentId={document.id}
                    pageIndex={index}
                    scale={
                      (Math.max(0.5, Math.ceil(camera.scale * 4) / 4) *
                        PAGE_WIDTH) /
                      size.width
                    }
                  />
                  {!editing ? (
                    <ReviewStatusMarkers
                      documentId={document.id}
                      pageIndex={index}
                      issues={locations.issues}
                      snapshot={snapshot}
                      selectedIssueId={selectedIssueId}
                      original={document.role === "original"}
                      coordinateScale={(PAGE_WIDTH / size.width) * camera.scale}
                      displayScale={camera.scale}
                      onSelect={onSelect}
                    />
                  ) : null}
                  {ring?.page === index + 1 ? (
                    <div
                      key={ring.requestId}
                      aria-hidden="true"
                      data-testid="pdf-attention-ring"
                      className={cn(styles.ring, attention.blink)}
                      style={{
                        left:
                          ring.target.origin.x -
                          frame.origin.x +
                          ring.target.size.width / 2,
                        top:
                          ring.target.origin.y -
                          frame.origin.y +
                          ring.target.size.height / 2,
                        width: 48 / camera.scale,
                        height: 48 / camera.scale,
                      }}
                    />
                  ) : null}
                </>
              ) : null}
            </div>
            {visible && overlayContainer
              ? createPortal(
                  <PagePointerProvider
                    documentId={document.id}
                    pageIndex={index}
                    scale={(camera.scale * PAGE_WIDTH) / size.width}
                    rotation={0}
                    data-pdf-annotation-page={index + 1}
                    data-annotation-document={document.id}
                    inert={
                      !editing ||
                      pan ||
                      !controller.ready ||
                      !snapshot ||
                      workspace.failed ||
                      !!workspace.openError
                    }
                    onPointerDownCapture={() => {
                      if (!controller.ready) return;
                      onActivate(document.id, index + 1);
                      controller.annotation?.setActiveTool(
                        tool === "select" ? null : tool
                      );
                    }}
                    style={{
                      position: "absolute",
                      left: camera.x + frame.origin.x * camera.scale,
                      top: camera.y + frame.origin.y * camera.scale,
                      width: frame.size.width * camera.scale,
                      height: frame.size.height * camera.scale,
                      pointerEvents: editing && !pan ? "auto" : "none",
                      zIndex: 10,
                    }}
                  >
                    <SelectionLayer
                      documentId={document.id}
                      pageIndex={index}
                      scale={(camera.scale * PAGE_WIDTH) / size.width}
                      rotation={0}
                    />
                    <AnnotationLayer
                      documentId={document.id}
                      pageIndex={index}
                      scale={(camera.scale * PAGE_WIDTH) / size.width}
                      rotation={0}
                    />
                  </PagePointerProvider>,
                  overlayContainer,
                  `${document.id}:${index}`
                )
              : null}
          </Fragment>
        );
      })}
    </>
  );
}

function CanvasPageImage({
  documentId,
  pageIndex,
  scale,
}: {
  documentId: string;
  pageIndex: number;
  scale: number;
}) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const { provides } = useRenderCapability();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [dpr, setDpr] = useState(1);
  const currentUrl = useRef<string | null>(null);
  useEffect(() => {
    let resolution: MediaQueryList | undefined;
    function updateDensity() {
      const density = window.devicePixelRatio || 1;
      setDpr(density);
      resolution?.removeEventListener("change", updateDensity);
      resolution = window.matchMedia(`(resolution: ${density}dppx)`);
      resolution.addEventListener("change", updateDensity);
    }
    updateDensity();
    window.addEventListener("resize", updateDensity);
    return () => {
      window.removeEventListener("resize", updateDensity);
      resolution?.removeEventListener("change", updateDensity);
    };
  }, []);
  useEffect(
    () => () => {
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
    },
    []
  );
  useEffect(() => {
    if (!provides) return;
    let alive = true;
    const task = provides.forDocument(documentId).renderPage({
      pageIndex,
      options: { scaleFactor: scale, dpr, withAnnotations: false },
    });
    setFailed(false);
    task.wait(
      (blob) => {
        if (!alive) return;
        const objectUrl = URL.createObjectURL(blob);
        if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
        currentUrl.current = objectUrl;
        setUrl(objectUrl);
      },
      () => {
        if (alive) setFailed(true);
      }
    );
    return () => {
      alive = false;
      task.abort({
        code: PdfErrorCode.Cancelled,
        message: "Canvas page render cancelled",
      });
    };
  }, [provides, documentId, pageIndex, scale, dpr, attempt]);
  return failed ? (
    <Section padding={4} gap={2}>
      <Text font="secondary-body" color="text-03">
        {t("loadFailed")}
      </Text>
      <Button size="sm" onClick={() => setAttempt((previous) => previous + 1)}>
        {t("retry")}
      </Button>
    </Section>
  ) : url ? (
    <img
      src={url}
      alt={t("evidencePage", { page: pageIndex + 1 })}
      draggable={false}
      className={styles.image}
    />
  ) : (
    <Section padding={4}>
      <Text font="secondary-body" color="text-03">
        {t("loading")}
      </Text>
    </Section>
  );
}
