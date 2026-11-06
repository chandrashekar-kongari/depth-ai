"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Document, Page, pdfjs } from "react-pdf";
import { Button, Text } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { Section } from "@opal/layouts";
import { cn } from "@opal/utils";
import type { DrawingFinding } from "@/app/app/services/streamingModels";
import { useDrawingReviewLayout } from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

const assetRoot = `/pdfjs/${pdfjs.version}/`;
pdfjs.GlobalWorkerOptions.workerSrc = `${assetRoot}pdf.worker.min.mjs`;
const DOCUMENT_OPTIONS = {
  cMapUrl: `${assetRoot}cmaps/`,
  cMapPacked: true,
  standardFontDataUrl: `${assetRoot}standard_fonts/`,
  wasmUrl: `${assetRoot}wasm/`,
  iccUrl: `${assetRoot}iccs/`,
  isEvalSupported: false,
};

const CATEGORY_ORDER = [
  "title_block",
  "views",
  "dimensions",
  "gdt",
  "bom",
  "cross_sheet",
] as const;

interface DrawingSheetMarksProps {
  sheetFileId: string | null;
  sheetFilename: string | null;
  pageCount: number;
  findings: DrawingFinding[];
  fill?: boolean;
  part?: "all" | "sheet" | "checklist";
}

function problemFindings(
  findings: DrawingFinding[],
  category: string
): DrawingFinding[] {
  return findings.filter(
    (finding) => finding.category === category && finding.status !== "pass"
  );
}

function groupStatus(problems: DrawingFinding[]): DrawingFinding["status"] {
  if (problems.some((finding) => finding.status === "fail")) {
    return "fail";
  }
  if (problems.length > 0) {
    return "needs_review";
  }
  return "pass";
}

function openProblemCategories(findings: DrawingFinding[]): Set<string> {
  return new Set(
    CATEGORY_ORDER.filter(
      (category) => problemFindings(findings, category).length > 0
    )
  );
}

function isPdfSheet(filename: string | null): boolean {
  return filename?.toLowerCase().endsWith(".pdf") ?? false;
}

function categoryLabel(
  category: string,
  t: ReturnType<typeof useTranslations<"chat.messages.drawingReview">>
): string {
  switch (category) {
    case "title_block":
      return t("categories.titleBlock.label");
    case "views":
      return t("categories.views.label");
    case "dimensions":
      return t("categories.dimensions.label");
    case "gdt":
      return t("categories.gdt.label");
    case "bom":
      return t("categories.bom.label");
    case "cross_sheet":
      return t("categories.crossSheet.label");
    default:
      return category;
  }
}

export function DrawingSheetMarks({
  sheetFileId,
  sheetFilename,
  pageCount,
  findings,
  fill = false,
  part = "all",
}: DrawingSheetMarksProps) {
  const t = useTranslations("chat.messages.drawingReview");
  const layout = useDrawingReviewLayout();
  const pdf = isPdfSheet(sheetFilename);
  const sheetFrameRef = useRef<HTMLDivElement>(null);
  const [localSelectedId, setLocalSelectedId] = useState<string | null>(null);
  const [localPageNumber, setLocalPageNumber] = useState(1);
  const selectedId = layout.active ? layout.selectedId : localSelectedId;
  const pageNumber = layout.active ? layout.pageNumber : localPageNumber;
  const [pageWidth, setPageWidth] = useState(480);
  const [openCategories, setOpenCategories] = useState<ReadonlySet<string>>(
    () => openProblemCategories(findings)
  );
  const [sheetFile, setSheetFile] = useState<{
    fileId: string;
    blob: Blob | null;
    failed: boolean;
  } | null>(null);

  useEffect(() => {
    if (part === "checklist" || !sheetFileId || !pdf) {
      return;
    }
    let cancelled = false;
    setSheetFile({ fileId: sheetFileId, blob: null, failed: false });
    fetch(`/api/chat/file/${encodeURIComponent(sheetFileId)}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("sheet");
        }
        return response.blob();
      })
      .then((blob) => {
        if (!cancelled) {
          setSheetFile({ fileId: sheetFileId, blob, failed: false });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSheetFile({ fileId: sheetFileId, blob: null, failed: true });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [part, sheetFileId, pdf]);

  useEffect(() => {
    const node = sheetFrameRef.current;
    if (node === null || typeof ResizeObserver === "undefined") {
      return;
    }
    const update = () => {
      const next = Math.floor(node.clientWidth);
      if (next > 0) {
        setPageWidth(next);
      }
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const totalPages = Math.max(pageCount, 1);
  const visiblePage = Math.min(Math.max(pageNumber, 1), totalPages);
  const pageFindings = findings.filter(
    (finding) => finding.page === visiblePage
  );
  const marks = pageFindings.filter(
    (finding) => finding.status !== "pass" && finding.box !== null
  );
  const hasProblem = findings.some((finding) => finding.status !== "pass");

  function selectFinding(finding: DrawingFinding) {
    if (layout.active) {
      layout.selectFinding(finding.id, finding.page);
      return;
    }
    setLocalSelectedId(finding.id);
    setLocalPageNumber(finding.page);
  }

  function changePage(page: number) {
    if (layout.active) {
      layout.setPageNumber(page);
      return;
    }
    setLocalPageNumber(page);
  }

  function statusLabel(status: DrawingFinding["status"]): string {
    if (status === "fail") {
      return t("failStatus.label");
    }
    if (status === "needs_review") {
      return t("needsReviewStatus.label");
    }
    return t("passStatus.label");
  }

  function toggleCategory(category: string) {
    setOpenCategories((current) => {
      const next = new Set(current);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  }

  const loadedFile =
    sheetFile !== null && sheetFile.fileId === sheetFileId ? sheetFile : null;
  const showChecklist = part !== "sheet";
  const showSheet = part !== "checklist";

  return (
    <Section
      flexDirection="column"
      alignItems="stretch"
      justifyContent="start"
      gap={2}
      width="full"
    >
      <Section
        flexDirection={showChecklist && showSheet ? "row" : "column"}
        alignItems={fill ? "stretch" : "start"}
        justifyContent="start"
        gap={2}
        width="full"
        className={fill ? "min-h-0" : undefined}
      >
        {showChecklist ? (
          <Section
            flexDirection="column"
            alignItems="stretch"
            justifyContent="start"
            gap={2}
            width={showSheet ? 18 : "full"}
            className={cn(
              showSheet && "shrink-0 border-r border-border-01",
              fill && "min-h-0 overflow-y-auto"
            )}
          >
            {findings.length === 0 || !hasProblem ? (
              <Text font="secondary-body" color="text-03">
                {t("noFindings.text")}
              </Text>
            ) : null}
            {CATEGORY_ORDER.map((category) => {
              const problems = problemFindings(findings, category);
              const expandable = problems.length > 0;
              const open = openCategories.has(category);
              const label = categoryLabel(category, t);
              return (
                <Section
                  key={category}
                  flexDirection="column"
                  alignItems="stretch"
                  justifyContent="start"
                  gap={1}
                  width="full"
                >
                  {expandable ? (
                    <Button
                      width="full"
                      size="sm"
                      prominence="tertiary"
                      aria-expanded={open}
                      onClick={() => toggleCategory(category)}
                    >
                      {label}
                    </Button>
                  ) : (
                    <Text font="secondary-body" color="text-04">
                      {label}
                    </Text>
                  )}
                  <Text font="secondary-body" color="text-03">
                    {statusLabel(groupStatus(problems))}
                  </Text>
                  {open
                    ? problems.map((finding) => (
                        <Section
                          key={finding.id}
                          flexDirection="column"
                          alignItems="stretch"
                          justifyContent="start"
                          gap={1}
                          width="full"
                        >
                          <Button
                            width="full"
                            size="sm"
                            prominence={
                              selectedId === finding.id ? "primary" : "tertiary"
                            }
                            aria-pressed={selectedId === finding.id}
                            onClick={() => selectFinding(finding)}
                          >
                            {finding.title}
                          </Button>
                          <Text font="secondary-body" color="text-03">
                            {statusLabel(finding.status)}
                          </Text>
                          {finding.standard_citation ? (
                            <Text font="secondary-body" color="text-04">
                              {t("standardCitation.text", {
                                citation: finding.standard_citation,
                              })}
                            </Text>
                          ) : null}
                        </Section>
                      ))
                    : null}
                </Section>
              );
            })}
          </Section>
        ) : null}
        {showSheet ? (
          <Section
            ref={sheetFrameRef}
            flexDirection="column"
            alignItems="stretch"
            justifyContent="start"
            gap={1}
            width="full"
            className={
              showChecklist
                ? "min-w-0 flex-1 basis-0 overflow-y-auto !w-auto"
                : "min-w-0 overflow-y-auto"
            }
          >
            {sheetFileId === null ? (
              <Text font="secondary-body" color="text-03">
                {t("noSheet.text")}
              </Text>
            ) : (
              <SheetPage
                sheetFileId={sheetFileId}
                pdf={pdf}
                blob={loadedFile?.blob ?? null}
                failed={loadedFile?.failed ?? false}
                pageNumber={visiblePage}
                marks={marks}
                selectedId={selectedId}
                pageWidth={pageWidth}
                onSelect={selectFinding}
                statusLabel={statusLabel}
              />
            )}
            {totalPages > 1 ? (
              <Section
                flexDirection="row"
                alignItems="center"
                justifyContent="between"
                width="full"
              >
                <Button
                  icon={SvgChevronLeft}
                  size="sm"
                  prominence="tertiary"
                  disabled={visiblePage <= 1}
                  onClick={() => changePage(visiblePage - 1)}
                >
                  {t("previousPage.label")}
                </Button>
                <Text font="secondary-body" color="text-03">
                  {t("pageOf.text", { page: visiblePage, total: totalPages })}
                </Text>
                <Button
                  icon={SvgChevronRight}
                  size="sm"
                  prominence="tertiary"
                  disabled={visiblePage >= totalPages}
                  onClick={() => changePage(visiblePage + 1)}
                >
                  {t("nextPage.label")}
                </Button>
              </Section>
            ) : null}
          </Section>
        ) : null}
      </Section>
    </Section>
  );
}

function SheetPage({
  sheetFileId,
  pdf,
  blob,
  failed,
  pageNumber,
  marks,
  selectedId,
  pageWidth,
  onSelect,
  statusLabel,
}: {
  sheetFileId: string;
  pdf: boolean;
  blob: Blob | null;
  failed: boolean;
  pageNumber: number;
  marks: DrawingFinding[];
  selectedId: string | null;
  pageWidth: number;
  onSelect: (finding: DrawingFinding) => void;
  statusLabel: (status: DrawingFinding["status"]) => string;
}) {
  const t = useTranslations("chat.messages.drawingReview");
  if (failed) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("sheetLoadFailed.text")}
      </Text>
    );
  }

  const pageMarks = [...marks].sort(
    (left, right) => Number(left.page_level) - Number(right.page_level)
  );

  return (
    <div className="relative w-full">
      {pdf ? (
        blob === null ? (
          <Text font="secondary-body" color="text-03">
            {t("reviewingStatus.text")}
          </Text>
        ) : (
          <Document
            file={blob}
            options={DOCUMENT_OPTIONS}
            loading={
              <Text font="secondary-body" color="text-03">
                {t("reviewingStatus.text")}
              </Text>
            }
          >
            <Page pageNumber={pageNumber} width={pageWidth} />
          </Document>
        )
      ) : (
        <img
          src={`/api/chat/file/${encodeURIComponent(sheetFileId)}`}
          alt={t("sheetImage.alt")}
          className="w-full"
        />
      )}
      {pageMarks.map((finding) => {
        const box = finding.box;
        if (box === null) {
          return null;
        }
        const selected = selectedId === finding.id;
        return (
          <div
            key={finding.id}
            data-finding-id={finding.id}
            data-selected={selected ? "true" : "false"}
            className={cn(
              "absolute overflow-hidden",
              finding.page_level && "pointer-events-none",
              selected
                ? "border-2 border-action-selection-02"
                : finding.status === "fail"
                  ? "border-2 border-status-error-05"
                  : "border-2 border-status-warning-05"
            )}
            style={{
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.width * 100}%`,
              height: `${box.height * 100}%`,
            }}
          >
            <div
              className={finding.page_level ? "pointer-events-auto" : undefined}
            >
              <Button
                size="2xs"
                width={finding.page_level ? "fit" : "full"}
                prominence="tertiary"
                variant={finding.status === "fail" ? "danger" : "default"}
                aria-label={t("markButton.label", { title: finding.title })}
                aria-pressed={selected}
                onClick={() => onSelect(finding)}
              >
                {finding.page_level
                  ? t("pageLevel.text")
                  : statusLabel(finding.status)}
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
