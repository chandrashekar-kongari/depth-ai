"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useDocumentState, useRegistry } from "@embedpdf/core/react";
import {
  useActiveDocument,
  useDocumentManagerCapability,
} from "@embedpdf/plugin-document-manager/react";
import {
  Viewport,
  useViewportCapability,
} from "@embedpdf/plugin-viewport/react";
import {
  Scroller,
  useScroll,
  useScrollCapability,
} from "@embedpdf/plugin-scroll/react";
import { RenderLayer } from "@embedpdf/plugin-render/react";
import { TilingLayer } from "@embedpdf/plugin-tiling/react";
import {
  AnnotationLayer,
  useAnnotation,
  useAnnotationCapability,
} from "@embedpdf/plugin-annotation/react";
import { SelectionLayer } from "@embedpdf/plugin-selection/react";
import { SearchLayer, useSearch } from "@embedpdf/plugin-search/react";
import { PagePointerProvider } from "@embedpdf/plugin-interaction-manager/react";
import { PanMode, usePan } from "@embedpdf/plugin-pan/react";
import { useRotate } from "@embedpdf/plugin-rotate/react";
import {
  useZoom,
  useZoomCapability,
  ZoomMode,
} from "@embedpdf/plugin-zoom/react";
import { useExportCapability } from "@embedpdf/plugin-export/react";
import { usePrintCapability } from "@embedpdf/plugin-print/react";
import { LockModeType } from "@embedpdf/plugin-annotation";
import type { PdfAnnotationObject } from "@embedpdf/models";
import {
  Button,
  InputSingleSelect,
  InputTypeIn,
  Popover,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgChevronLeft,
  SvgChevronRight,
  SvgDownload,
  SvgEdit,
  SvgSearch,
  SvgMoreHorizontal,
  SvgFitWidth,
  SvgTrash,
  SvgZoomIn,
  SvgZoomOut,
} from "@opal/icons";
import { cn } from "@opal/utils";
import { ReviewStatusMarkers } from "@/lib/pdf-review/ReviewStatusMarkers";
import { resolvedAnchor, locationKey } from "@/lib/pdf-review/anchors";
import { rectAnchor } from "@/lib/pdf-review/geometry";
import { revealIssue } from "@/lib/pdf-review/revealIssue";
import { issueFocusTarget } from "@/lib/pdf-review/navigation";
import { PdfEngineProvider } from "@/lib/pdf-review/embedpdf/provider";
import {
  encodeAppearance,
  reconcileAnnotations,
} from "@/lib/pdf-review/embedpdf/adapter";
import {
  AttentionRing,
  scheduleAttentionEnd,
} from "@/lib/pdf-review/AttentionRing";
import { useTextLocations } from "@/lib/pdf-review/useTextLocations";
import { useDrawingWorkspace } from "@/lib/pdf-review/hooks";
import type {
  LinkedIssue,
  PdfReviewWorkspaceProps,
} from "@/lib/pdf-review/types";

export function PdfReviewWorkspace(props: PdfReviewWorkspaceProps) {
  const pdfs = props.documents.filter((document) =>
    document.filename.toLowerCase().endsWith(".pdf")
  );
  const t = useTranslations("chat.messages.pdfWorkspace");
  const [imageId, setImageId] = useState(props.documents[0]?.id);
  if (pdfs.length !== props.documents.length) {
    const image =
      props.documents.find((document) => document.id === imageId) ??
      props.documents[0];
    return (
      <Section
        height={props.fill ? "full" : "fit"}
        justifyContent="start"
        alignItems="stretch"
      >
        <Section flexDirection="row" height="fit" gap={1}>
          {props.documents.map((document) => (
            <Button
              key={document.id}
              aria-pressed={document.id === image?.id}
              onClick={() => setImageId(document.id)}
            >
              {document.label}
            </Button>
          ))}
        </Section>
        {image ? (
          <img
            src={image.url}
            alt={image.filename}
            className="min-h-0 w-full object-contain"
          />
        ) : (
          <Text font="secondary-body" color="text-03">
            {t("loadFailed")}
          </Text>
        )}
      </Section>
    );
  }
  return (
    <PdfEngineProvider documents={props.documents}>
      <Workspace {...props} />
    </PdfEngineProvider>
  );
}

function Workspace({
  documents,
  pageNumber,
  onPageChange,
  issues: inputIssues = [],
  selectedIssueId,
  focusRequest,
  onIssueSelect,
  fill = false,
}: PdfReviewWorkspaceProps) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const ui = useTranslations("chat.workspace");
  const [annotationMode, setAnnotationMode] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const { pluginsReady } = useRegistry();
  const { activeDocumentId } = useActiveDocument();
  const id = activeDocumentId ?? documents[0]?.id ?? "";
  const descriptor =
    documents.find((document) => document.id === id) ?? documents[0];
  const documentState = useDocumentState(id);
  const { provides: manager } = useDocumentManagerCapability();
  const { provides: viewportCapability } = useViewportCapability();
  const { state: annotationState } = useAnnotation(id);
  const { provides: annotationCapability } = useAnnotationCapability();
  const annotation = useMemo(
    () => annotationCapability?.forDocument(id) ?? null,
    [annotationCapability, id]
  );
  const { state: zoomState } = useZoom(id);
  const { provides: zoomCapability } = useZoomCapability();
  const zoom = useMemo(
    () => zoomCapability?.forDocument(id) ?? null,
    [zoomCapability, id]
  );
  const { state: scrollState } = useScroll(id);
  const { provides: scrollCapability } = useScrollCapability();
  const scroll = useMemo(
    () => scrollCapability?.forDocument(id) ?? null,
    [scrollCapability, id]
  );
  const { provides: pan, isPanning } = usePan(id);
  const { provides: rotate } = useRotate(id);
  const { provides: search, state: searchState } = useSearch(id);
  const { provides: exporter } = useExportCapability();
  const { provides: printer } = usePrintCapability();
  const {
    snapshot,
    openError,
    pending,
    failed,
    submit,
    retry,
    reload,
    reopen,
  } = useDrawingWorkspace(documents.map((document) => document.id));
  const locations = useTextLocations(
    snapshot,
    id,
    inputIssues,
    descriptor?.role
  );
  const issues = locations.issues;
  const [query, setQuery] = useState("");
  const navigationRequest = focusRequest;
  const handledFocus = useRef<string | null>(null);
  const [radar, setRadar] = useState<{
    requestId: string;
    documentId: string;
    page: number;
    rect: import("@embedpdf/models").Rect;
  } | null>(null);
  useEffect(() => {
    if (!radar) return;
    return scheduleAttentionEnd(() => setRadar(null));
  }, [radar]);
  const correctionIssue = useRef<LinkedIssue | null>(null);
  const [correcting, setCorrecting] = useState(false);
  const discarded = useRef(new Set<string>());
  const cancelNavigation = useRef<(() => void) | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportFailed, setExportFailed] = useState(false);
  const [content, setContent] = useState("");
  const [hydratedId, setHydratedId] = useState<string | null>(null);
  const suppress = useRef(false);
  const managedByDocument = useRef(new Map<string, Set<string>>());
  const originalsByDocument = useRef(
    new Map<string, Map<string, PdfAnnotationObject>>()
  );
  const appliedVersions = useRef(new Map<string, string>());
  const syncPage = useRef(onPageChange);
  useEffect(() => {
    syncPage.current = onPageChange;
  }, [onPageChange]);
  const reviewKey = JSON.stringify(issues);
  const issuesRef = useRef(issues);
  useEffect(() => {
    issuesRef.current = issues;
  }, [issues]);
  const selected = annotationState.selectedUid
    ? annotationState.byUid[annotationState.selectedUid]?.object
    : null;
  useEffect(() => {
    if (!selected) return;
    const issue = issuesRef.current.find((item) =>
      selected.id.startsWith(`depth-review:${locationKey(item)}:`)
    );
    if (issue && issue.id !== selectedIssueId)
      onIssueSelect?.(issue.id, selected.pageIndex + 1);
  }, [selected, selectedIssueId, onIssueSelect]);
  const currentPage = scrollState.currentPage || 1;
  const total = documentState?.document?.pageCount ?? 1;
  const editable =
    !!snapshot && hydratedId === id && !failed && !openError && !exporting;

  useEffect(() => {
    if (annotation)
      annotation.setLocked(
        editable ? { type: LockModeType.None } : { type: LockModeType.All }
      );
  }, [annotation, editable]);
  useEffect(() => {
    setContent(selected?.contents ?? "");
  }, [selected?.id, selected?.contents]);
  useEffect(() => {
    if (!scroll || !pluginsReady) return;
    return scroll.onPageChange((event) => syncPage.current(event.pageNumber));
  }, [scroll, pluginsReady]);
  useEffect(() => {
    if (
      !navigationRequest ||
      handledFocus.current === navigationRequest.id ||
      !manager ||
      !pluginsReady
    )
      return;
    if (
      !documents.some(
        (document) => document.id === navigationRequest.documentId
      )
    )
      return;
    if (id !== navigationRequest.documentId) {
      manager.setActiveDocument(navigationRequest.documentId);
      return;
    }
    if (!documentState?.document || !scroll || !scrollCapability) return;
    const target = issueFocusTarget(
      navigationRequest,
      issuesRef.current,
      documentState.document,
      snapshot
    );
    const cancel = revealIssue({
      documentId: id,
      target,
      scroll,
      ready: scrollCapability.onLayoutReady,
      changed: scroll.onScroll,
      isVisible: () => scroll.getMetrics().visiblePages.includes(target.page),
      canReveal: () => {
        const metrics = viewportCapability?.forDocument(id).getMetrics();
        return !!metrics && metrics.clientWidth > 0 && metrics.clientHeight > 0;
      },
      onReveal: () => {
        if (!locations.isLoading) handledFocus.current = navigationRequest.id;
        syncPage.current(target.page);
        if (target.rect)
          setRadar({
            requestId: navigationRequest.id,
            documentId: id,
            page: target.page,
            rect: target.rect,
          });
      },
    });
    cancelNavigation.current = () => {
      handledFocus.current = navigationRequest.id;
      cancel();
    };
    return () => {
      cancel();
      cancelNavigation.current = null;
    };
  }, [
    navigationRequest,
    id,
    manager,
    documents,
    documentState?.document,
    snapshot,
    scroll,
    scrollCapability,
    viewportCapability,
    locations.isLoading,
    reviewKey,
    annotation,
    hydratedId,
    pluginsReady,
  ]);
  const lastSelection = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (
      navigationRequest ||
      !scroll ||
      !selectedIssueId ||
      selectedIssueId === lastSelection.current
    )
      return;
    lastSelection.current = selectedIssueId;
    const issue = issues.find((item) => item.id === selectedIssueId);
    const anchor = issue ? resolvedAnchor(snapshot, id, issue) : null;
    scroll.scrollToPage({
      pageNumber: anchor?.page ?? pageNumber,
      behavior: "instant",
    });
  }, [
    id,
    issues,
    pageNumber,
    scroll,
    selectedIssueId,
    snapshot,
    navigationRequest,
  ]);

  useEffect(() => {
    if (
      !snapshot ||
      !annotation ||
      documentState?.status !== "loaded" ||
      pending ||
      appliedVersions.current.get(id) === `${snapshot.version}:${reviewKey}`
    )
      return;
    let alive = true;
    setHydratedId(null);
    suppress.current = true;
    const firstRead = !originalsByDocument.current.has(id);
    const managed = managedByDocument.current.get(id) ?? new Set<string>();
    const originals =
      originalsByDocument.current.get(id) ??
      new Map<string, PdfAnnotationObject>();
    managedByDocument.current.set(id, managed);
    originalsByDocument.current.set(id, originals);
    const records = snapshot.state.annotations[id] ?? {};
    reconcileAnnotations(
      annotation,
      records,
      originals,
      managed,
      firstRead
        ? (documentState.document?.pages.map((page) => page.index) ?? [])
        : []
    )
      .then(() => {
        if (!alive) return;
        appliedVersions.current.set(id, `${snapshot.version}:${reviewKey}`);
        setHydratedId(id);
        // Durable workspace commands own undo; discard the SDK replay history.
      })
      .catch(() => {
        if (alive) setExportFailed(true);
      })
      .finally(() => {
        if (alive) suppress.current = false;
      });
    return () => {
      alive = false;
    };
  }, [
    snapshot,
    id,
    annotation,
    documentState?.status,
    documentState?.document,
    pending,
    reviewKey,
  ]);

  useEffect(() => {
    if (!annotation || !snapshot) return;
    return annotation.onAnnotationEvent((event) => {
      if (suppress.current || event.type === "loaded" || event.committed)
        return;
      if (
        event.type !== "create" &&
        event.type !== "update" &&
        event.type !== "delete"
      )
        return;
      managedByDocument.current.set(
        id,
        new Set([
          ...(managedByDocument.current.get(id) ?? []),
          event.annotation.id,
        ])
      );
      if (discarded.current.has(event.annotation.id)) return;
      const issue = issuesRef.current.find(
        (item) =>
          event.annotation.id === `depth-review:${locationKey(item)}:region`
      );
      const correcting =
        event.type === "create" ? correctionIssue.current : issue;
      if (correcting && event.type !== "delete") {
        const page = documentState?.document?.pages[event.pageIndex];
        if (!page) return;
        const anchor = rectAnchor(
          event.annotation.rect,
          page.size,
          event.pageIndex + 1
        );
        if (!anchor) return;
        submit({
          action: "set_anchor",
          document_id: id,
          issue_id: locationKey(correcting),
          anchor,
        });
        if (correctionIssue.current) {
          correctionIssue.current = null;
          setCorrecting(false);
          discarded.current.add(event.annotation.id);
          annotation.deleteAnnotation(event.pageIndex, event.annotation.id);
          annotation.setActiveTool(null);
        }
        return;
      }
      if (event.type === "delete") {
        submit({
          action: "delete_annotation",
          document_id: id,
          annotation_id: event.annotation.id,
          annotation: event.annotation,
        });
        return;
      }
      if (event.annotation.type === 13) {
        void annotation
          .exportAnnotations({ pageIndex: event.pageIndex })
          .toPromise()
          .then((items) => {
            const item = items.find(
              (item) => item.annotation.id === event.annotation.id
            );
            const appearance =
              item?.ctx &&
              "data" in item.ctx &&
              item.ctx.data instanceof ArrayBuffer
                ? encodeAppearance(item.ctx.data)
                : null;
            submit({
              action: "upsert_annotation",
              document_id: id,
              annotation: event.annotation,
              appearance,
            });
          });
      } else
        submit({
          action: "upsert_annotation",
          document_id: id,
          annotation: event.annotation,
        });
    });
  }, [id, annotation, snapshot, submit, documentState?.document]);

  function switchDocument(next: string) {
    if (pending) return;
    cancelNavigation.current?.();
    correctionIssue.current = null;
    setCorrecting(false);
    annotation?.setActiveTool(null);
    manager?.setActiveDocument(next);
    lastSelection.current = undefined;
  }
  async function download() {
    if (!annotation || !exporter || !descriptor) return;
    setExporting(true);
    setExportFailed(false);
    try {
      await annotation.commit().toPromise();
      const bytes = await exporter.forDocument(id).saveAsCopy().toPromise();
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
  function keyboard(event: React.KeyboardEvent) {
    if (
      event.target instanceof HTMLElement &&
      event.target.closest("input,textarea,[contenteditable=true]")
    )
      return;
    if (
      (event.ctrlKey || event.metaKey) &&
      ["z", "y"].includes(event.key.toLowerCase())
    ) {
      event.preventDefault();
      event.stopPropagation();
      if (pending || !editable) return;
      const redo = event.key.toLowerCase() === "y" || event.shiftKey;
      if (redo ? snapshot?.can_redo : snapshot?.can_undo)
        submit({ action: redo ? "redo" : "undo" });
    }
    if (event.key === "Escape") {
      correctionIssue.current = null;
      setCorrecting(false);
      cancelNavigation.current?.();
      annotation?.setActiveTool(null);
      pan?.disablePan();
    }
    if (
      (event.key === "Delete" || event.key === "Backspace") &&
      selected &&
      editable
    ) {
      event.preventDefault();
      annotation?.deleteAnnotation(selected.pageIndex, selected.id);
    }
  }
  const tool = annotationState.activeToolId ?? "select";
  return (
    <Section
      onKeyDownCapture={keyboard}
      onWheelCapture={() => cancelNavigation.current?.()}
      onPointerDownCapture={() => cancelNavigation.current?.()}
      tabIndex={0}
      aria-label={t("markupLayer")}
      height={fill ? "full" : undefined}
      gap={0}
      justifyContent="start"
      alignItems="stretch"
      className={cn(
        "min-h-0 overflow-hidden bg-background-neutral-01",
        !fill && "rounded-12 border border-border-01"
      )}
    >
      <Section
        flexDirection="row"
        height="fit"
        padding={2}
        gap={2}
        wrap
        justifyContent="between"
        className="depth-pdf-toolbar shrink-0 border-b border-border-01"
      >
        <Section flexDirection="row" width="fit" height="fit" gap={1}>
          {documents.map((document) => (
            <Button
              key={document.id}
              size="sm"
              disabled={!!pending}
              prominence={document.id === id ? "secondary" : "tertiary"}
              aria-pressed={document.id === id}
              tooltip={document.filename}
              onClick={() => switchDocument(document.id)}
            >
              {document.label}
            </Button>
          ))}
        </Section>
        <Section flexDirection="row" width="fit" height="fit" gap={1} wrap>
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgChevronLeft}
            aria-label={t("previous")}
            tooltip={t("previous")}
            disabled={currentPage <= 1}
            onClick={() => scroll?.scrollToPreviousPage()}
          />
          <Section width={3} height="fit">
            <InputTypeIn
              type="number"
              aria-label={t("page")}
              value={String(currentPage)}
              min={1}
              max={total}
              onChange={(event) => {
                const value = Number(event.target.value);
                if (value >= 1 && value <= total) {
                  scroll?.scrollToPage({ pageNumber: value });
                  syncPage.current(value);
                }
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
            tooltip={t("next")}
            disabled={currentPage >= total}
            onClick={() => scroll?.scrollToNextPage()}
          />
          <Popover>
            <Popover.Trigger asChild>
              <Button size="sm" prominence="tertiary">
                {t("zoom", {
                  percent: Math.round(zoomState.currentZoomLevel * 100),
                })}
              </Button>
            </Popover.Trigger>
            <Popover.Content align="end">
              <Section
                height="fit"
                width="fit"
                alignItems="stretch"
                gap={1}
                padding={1}
              >
                <Section flexDirection="row" height="fit" gap={2}>
                  <Button
                    size="sm"
                    prominence="tertiary"
                    icon={SvgZoomOut}
                    aria-label={t("zoomOut")}
                    onClick={() => zoom?.zoomOut()}
                  />
                  <Button
                    size="sm"
                    prominence="tertiary"
                    icon={SvgZoomIn}
                    aria-label={t("zoomIn")}
                    onClick={() => zoom?.zoomIn()}
                  />
                </Section>
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgFitWidth}
                  onClick={() => zoom?.requestZoom(ZoomMode.FitWidth)}
                >
                  {t("fitWidth")}
                </Button>
                <Button
                  size="sm"
                  prominence="tertiary"
                  onClick={() => zoom?.requestZoom(ZoomMode.FitPage)}
                >
                  {t("fitPage")}
                </Button>
              </Section>
            </Popover.Content>
          </Popover>
          <Button
            size="sm"
            prominence={annotationMode ? "secondary" : "tertiary"}
            icon={SvgEdit}
            aria-pressed={annotationMode}
            onClick={() => {
              setAnnotationMode(!annotationMode);
              if (annotationMode) {
                correctionIssue.current = null;
                setCorrecting(false);
                annotation?.setActiveTool(null);
              }
            }}
          >
            {ui("annotate")}
          </Button>
          <Button
            size="sm"
            prominence={searchOpen ? "secondary" : "tertiary"}
            icon={SvgSearch}
            aria-label={t("search")}
            tooltip={t("search")}
            aria-expanded={searchOpen}
            onClick={() => setSearchOpen(!searchOpen)}
          />
          <Popover>
            <Popover.Trigger asChild>
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgMoreHorizontal}
                aria-label={ui("moreActions")}
                tooltip={ui("moreActions")}
              />
            </Popover.Trigger>
            <Popover.Content align="end">
              <Section
                height="fit"
                width="fit"
                alignItems="stretch"
                gap={1}
                padding={1}
              >
                <Button
                  size="sm"
                  prominence="tertiary"
                  onClick={() => rotate?.rotateForward()}
                >
                  {t("rotate")}
                </Button>
                <Button
                  size="sm"
                  prominence={isPanning ? "secondary" : "tertiary"}
                  aria-pressed={isPanning}
                  onClick={() => {
                    annotation?.setActiveTool(null);
                    pan?.togglePan();
                  }}
                >
                  {t("pan")}
                </Button>
                <Button
                  size="sm"
                  prominence="tertiary"
                  disabled={!editable || !!pending}
                  onClick={() =>
                    void printer
                      ?.forDocument(id)
                      .print()
                      .toPromise()
                      .catch(() => setExportFailed(true))
                  }
                >
                  {t("print")}
                </Button>
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgDownload}
                  disabled={!editable || !!pending || exporting}
                  onClick={download}
                >
                  {t(exporting ? "exporting" : "export")}
                </Button>
                {locations.data?.some(
                  (item) => item.status === "located_text"
                ) ? (
                  <Section width={60} height="fit" padding={2}>
                    <Text font="secondary-body" color="text-03">
                      {t("textLocationNotice")}
                    </Text>
                  </Section>
                ) : null}
              </Section>
            </Popover.Content>
          </Popover>
        </Section>
      </Section>
      {annotationMode ? (
        <Section
          flexDirection="row"
          height="fit"
          padding={2}
          gap={2}
          wrap
          justifyContent="start"
          className="shrink-0 border-b border-border-01"
        >
          <Section width={10} height="fit">
            <InputSingleSelect
              placeholder={t("tools")}
              defaultOption="select"
              value={tool}
              onValueChange={(value) => {
                correctionIssue.current = null;
                setCorrecting(false);
                pan?.disablePan();
                annotation?.setActiveTool(value === "select" ? null : value);
              }}
              options={[
                { value: "select", title: t("select") },
                { value: "highlight", title: t("highlight") },
                { value: "ink", title: t("ink") },
                { value: "inkHighlighter", title: t("inkHighlighter") },
                { value: "square", title: t("rectangle") },
                { value: "circle", title: t("ellipse") },
                { value: "lineArrow", title: t("arrow") },
                { value: "freeText", title: t("freeText") },
                { value: "freeTextCallout", title: t("callout") },
                { value: "textComment", title: t("note") },
                { value: "underline", title: t("underline") },
                { value: "strikeout", title: t("strikeout") },
              ]}
            />
          </Section>
          <Button
            size="sm"
            prominence="tertiary"
            disabled={!editable || !!pending || !snapshot?.can_undo}
            onClick={() => submit({ action: "undo" })}
          >
            {t("undo")}
          </Button>
          <Button
            size="sm"
            prominence="tertiary"
            disabled={!editable || !!pending || !snapshot?.can_redo}
            onClick={() => submit({ action: "redo" })}
          >
            {t("redo")}
          </Button>
          <Button
            size="sm"
            icon={SvgTrash}
            aria-label={t("delete")}
            disabled={!editable || !selected}
            onClick={() => {
              if (selected)
                annotation?.deleteAnnotation(selected.pageIndex, selected.id);
            }}
          />
        </Section>
      ) : null}
      {searchOpen ? (
        <Section
          flexDirection="row"
          height="fit"
          padding={2}
          gap={2}
          justifyContent="start"
          className="shrink-0 border-b border-border-01"
        >
          <Section width={12} height="fit">
            <InputTypeIn
              searchIcon
              aria-label={t("search")}
              placeholder={t("search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  search?.startSearch();
                  void search?.searchAllPages(query);
                }
              }}
            />
          </Section>
          <Button
            size="sm"
            disabled={!searchState.total}
            onClick={() => search?.nextResult()}
          >
            {t("matches", { count: searchState.total })}
          </Button>
        </Section>
      ) : null}
      {locations.error ? (
        <Text font="secondary-body" color="text-03">
          {t("textLocationError")}
        </Text>
      ) : null}
      {selectedIssueId ? (
        <Section
          flexDirection="row"
          justifyContent="start"
          height="fit"
          gap={1}
          padding={2}
          className="shrink-0 border-b border-border-01"
        >
          <Button
            prominence="tertiary"
            size="sm"
            disabled={!editable || !!pending}
            onClick={() => {
              const issue = issues.find((item) => item.id === selectedIssueId);
              if (!issue) return;
              correctionIssue.current = issue;
              setCorrecting(true);
              setAnnotationMode(true);
              pan?.disablePan();
              annotation?.deselectAnnotation();
              annotation?.setActiveTool("square");
            }}
          >
            {t("correctLocation")}
          </Button>
          <Button
            prominence="tertiary"
            size="sm"
            disabled={
              !issues.some(
                (item) =>
                  item.id === selectedIssueId &&
                  resolvedAnchor(snapshot, id, item)
              )
            }
            onClick={() =>
              zoom?.requestZoom(
                Math.max(
                  zoomState.currentZoomLevel,
                  Math.min(2, zoomState.currentZoomLevel * 1.5)
                )
              )
            }
          >
            {t("inspectDetail")}
          </Button>
        </Section>
      ) : null}
      {selected && !selected.id.startsWith("depth-review:") ? (
        <Section
          flexDirection="row"
          height="fit"
          padding={2}
          gap={2}
          className="shrink-0"
        >
          <InputTypeIn
            aria-label={t("noteText")}
            value={content}
            maxLength={10000}
            onChange={(event) => setContent(event.target.value)}
          />
          <Button
            size="sm"
            disabled={!editable}
            onClick={() =>
              annotation?.updateAnnotation(selected.pageIndex, selected.id, {
                contents: content,
              })
            }
          >
            {t("saveNote")}
          </Button>
        </Section>
      ) : null}
      <div
        className={cn("relative min-h-0 w-full", fill ? "flex-1" : "h-[65vh]")}
      >
        <PanMode />
        {documentState?.status === "loaded" ? (
          <Viewport
            documentId={id}
            className="h-full w-full bg-background-neutral-02"
          >
            <Scroller
              documentId={id}
              renderPage={({ pageIndex, rotatedWidth, rotatedHeight }) => (
                <PagePointerProvider
                  documentId={id}
                  pageIndex={pageIndex}
                  style={{ width: rotatedWidth, height: rotatedHeight }}
                  className="relative bg-background-neutral-01 shadow-lg"
                >
                  <RenderLayer
                    documentId={id}
                    pageIndex={pageIndex}
                    scale={0.75}
                    className="pointer-events-none"
                  />
                  <TilingLayer documentId={id} pageIndex={pageIndex} />
                  <SelectionLayer documentId={id} pageIndex={pageIndex} />
                  <SearchLayer documentId={id} pageIndex={pageIndex} />
                  <AnnotationLayer documentId={id} pageIndex={pageIndex} />
                  {!annotationMode ? <ReviewStatusMarkers documentId={id} pageIndex={pageIndex} issues={issues} snapshot={snapshot} selectedIssueId={selectedIssueId} original={descriptor?.role === "original"} onSelect={(issueId,page)=>onIssueSelect?.(issueId,page)} /> : null}
                  {radar?.documentId === id && radar.page === pageIndex + 1 ? (
                    <AttentionRing
                      key={radar.requestId}
                      documentId={id}
                      pageIndex={pageIndex}
                      rect={radar.rect}
                    />
                  ) : null}
                </PagePointerProvider>
              )}
            />
          </Viewport>
        ) : (
          <Section padding={4}>
            <Text font="secondary-body" color="text-03">
              {t(documentState?.status === "error" ? "loadFailed" : "loading")}
            </Text>
          </Section>
        )}
      </div>
      <Section
        flexDirection="row"
        height="fit"
        padding={2}
        gap={2}
        wrap
        justifyContent="between"
        className="shrink-0 border-t border-border-01"
      >
        <Text font="secondary-body" color="text-03">
          {t(
            correcting
              ? "placeAnchor"
              : openError || failed
                ? "saveFailed"
                : pending
                  ? "saving"
                  : snapshot
                    ? "saved"
                    : "loading"
          )}
        </Text>
        {openError ? (
          <Button size="sm" prominence="tertiary" onClick={() => void reopen()}>
            {t("retry")}
          </Button>
        ) : failed ? (
          <Section flexDirection="row" width="fit" height="fit" gap={1}>
            <Button size="sm" onClick={() => void retry()}>
              {t("retry")}
            </Button>
            <Button
              size="sm"
              prominence="tertiary"
              onClick={() => {
                appliedVersions.current.clear();
                void reload();
              }}
            >
              {t("reloadSaved")}
            </Button>
          </Section>
        ) : null}
        {exportFailed ? (
          <Text font="secondary-body" color="text-02">
            {t("exportFailed")}
          </Text>
        ) : null}
      </Section>
    </Section>
  );
}
