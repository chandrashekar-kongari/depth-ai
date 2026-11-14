"use client";

/* oxlint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- The application surface provides keyboard camera controls. */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useDocumentState } from "@embedpdf/core/react";
import { useDocumentManagerCapability } from "@embedpdf/plugin-document-manager/react";
import { useRenderCapability } from "@embedpdf/plugin-render/react";
import { PdfErrorCode, type Rect, type Size } from "@embedpdf/models";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgChevronLeft,
  SvgChevronRight,
  SvgEdit,
  SvgFitWidth,
  SvgZoomIn,
  SvgZoomOut,
} from "@opal/icons";
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
import attention from "@/lib/pdf-review/attention.module.css";
import { scheduleAttentionEnd } from "@/lib/pdf-review/AttentionRing";

interface PdfCanvasProps extends PdfReviewWorkspaceProps {
  editor: ReactNode;
}

export function PdfCanvas({
  documents,
  issues = [],
  focusRequest,
  selectedIssueId,
  onIssueSelect,
  pageNumber,
  onPageChange,
  fill,
  editor,
}: PdfCanvasProps) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const ui = useTranslations("chat.workspace");
  const root = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  const [camera, setCamera] = useState<CanvasCamera>({
    x: 32,
    y: 64,
    scale: 0.5,
  });
  const [geometry, setGeometry] = useState<Record<string, Size[]>>({});
  const [activeId, setActiveId] = useState(documents[0]?.id ?? "");
  const [editing, setEditing] = useState(false);
  const [pan, setPan] = useState(false);
  const [space, setSpace] = useState(false);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ id: number; x: number; y: number } | null>(null);
  const [localFocus, setLocalFocus] = useState<ReviewFocusRequest | null>(null);
  const request = localFocus ?? focusRequest;
  const cancelled = useRef<string | null>(null);
  const initialFit = useRef(false);
  const { provides: manager } = useDocumentManagerCapability();
  const { snapshot, reload } = useDrawingWorkspace(
    documents.map((document) => document.id)
  );

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
      fitCamera(size, {
        origin: { x: 0, y: 0 },
        size: {
          width: documents.length * (PAGE_WIDTH + COLUMN_GAP) - COLUMN_GAP,
          height: Math.max(...frames.map((frame) => frame.size.height)) + 48,
        },
      })
    );
  }, [documents, geometry, size]);
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
      setCamera((previous) => centerCamera(previous, size, target));
      setActiveId(next.documentId);
      manager?.setActiveDocument(next.documentId);
      onPageChange(next.page);
      return true;
    },
    [size, manager, onPageChange]
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
      centerCamera(previous, size, pageFrame(pages, column, next - 1))
    );
    setActiveId(documentId);
    manager?.setActiveDocument(documentId);
    onPageChange(next);
  }
  function zoom(factor: number) {
    cancelFocus();
    setCamera((previous) =>
      zoomCamera(previous, previous.scale * factor, {
        x: size.width / 2,
        y: size.height / 2,
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
      {editing ? (
        <>
          <Section
            flexDirection="row"
            height="fit"
            padding={2}
            justifyContent="start"
          >
            <Button
              size="sm"
              onClick={() => {
                setEditing(false);
                void reload();
              }}
            >
              {t("backToCanvas")}
            </Button>
          </Section>
          {editor}
        </>
      ) : null}
      <Section
        hidden={editing}
        height={fill ? "full" : undefined}
        alignItems="stretch"
        justifyContent="start"
        gap={0}
        className="min-h-0 flex-1"
      >
        <Section
          flexDirection="row"
          height="fit"
          padding={2}
          gap={1}
          wrap
          justifyContent="between"
          className="shrink-0 border-b border-border-01"
        >
          <Section flexDirection="row" width="fit" height="fit" gap={1} wrap>
            {documents.map((document) => (
              <Button
                key={document.id}
                size="sm"
                prominence={activeId === document.id ? "secondary" : "tertiary"}
                aria-pressed={activeId === document.id}
                tooltip={document.filename}
                onClick={() => navigate(document.id, pageNumber)}
              >
                {document.label}
              </Button>
            ))}
          </Section>
          <Section flexDirection="row" width="fit" height="fit" gap={1} wrap>
            <Button
              size="sm"
              prominence={!pan ? "secondary" : "tertiary"}
              aria-pressed={!pan}
              onClick={() => setPan(false)}
            >
              {t("select")}
            </Button>
            <Button
              size="sm"
              prominence={pan ? "secondary" : "tertiary"}
              aria-pressed={pan}
              onClick={() => setPan(true)}
            >
              {t("pan")}
            </Button>
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgEdit}
              onClick={() => {
                cancelFocus();
                setEditing(true);
              }}
            >
              {ui("annotate")}
            </Button>
          </Section>
        </Section>
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
            }
            if (event.key === "+" || event.key === "=") {
              event.preventDefault();
              zoom(1.2);
            }
            if (event.key === "-") {
              event.preventDefault();
              zoom(1 / 1.2);
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
                event.pointerType === "touch" ||
                (event.target instanceof HTMLElement &&
                  !event.target.closest("[data-pdf-document]"))
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
        <Section
          flexDirection="row"
          height="fit"
          padding={2}
          gap={1}
          wrap
          justifyContent="between"
          className="shrink-0 border-t border-border-01"
        >
          <Section flexDirection="row" width="fit" height="fit" gap={1}>
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgChevronLeft}
              aria-label={t("previous")}
              disabled={pageNumber <= 1}
              onClick={() => navigate(activeId, pageNumber - 1)}
            />
            <Section width={3} height="fit">
              <InputTypeIn
                type="number"
                min={1}
                max={total}
                aria-label={t("page")}
                value={String(Math.min(pageNumber, total))}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isInteger(value) && value >= 1 && value <= total)
                    navigate(activeId, value);
                }}
              />
            </Section>
            <Text font="secondary-body" color="text-03">
              {t("ofPages", { total })}
            </Text>
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgChevronRight}
              aria-label={t("next")}
              disabled={pageNumber >= total}
              onClick={() => navigate(activeId, pageNumber + 1)}
            />
          </Section>
          <Section flexDirection="row" width="fit" height="fit" gap={1}>
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgZoomOut}
              aria-label={t("zoomOut")}
              onClick={() => zoom(1 / 1.2)}
            />
            <Text font="secondary-body" color="text-03">
              {t("zoom", { percent: Math.round(camera.scale * 100) })}
            </Text>
            <Button
              size="sm"
              prominence="tertiary"
              icon={SvgZoomIn}
              aria-label={t("zoomIn")}
              onClick={() => zoom(1.2)}
            />
            {documents.length > 1 ? (
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgFitWidth}
                onClick={() => {
                  cancelFocus();
                  fitAll();
                }}
              >
                {t("fitAll")}
              </Button>
            ) : null}
            <Button
              size="sm"
              prominence="tertiary"
              onClick={() => {
                const pages = geometry[activeId];
                if (pages?.length) {
                  cancelFocus();
                  setCamera(
                    fitCamera(
                      size,
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
            >
              {t("fitPage")}
            </Button>
          </Section>
        </Section>
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
          <div
            key={index}
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
              <Section flexDirection="row" width="fit" height="fit" gap={2}>
                <Text font="secondary-body" color="text-03">
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
      options: { scaleFactor: scale, dpr, withAnnotations: true },
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
