"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Divider,
  InputTypeIn,
  Popover,
  Text,
  Tooltip,
} from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgChevronDownSmall,
  SvgChevronLeft,
  SvgChevronRight,
  SvgEdit,
  SvgFiles,
  SvgFitWidth,
  SvgZoomIn,
  SvgZoomOut,
  SvgCursor,
  SvgHand,
} from "@opal/icons";
import {
  CanvasAnnotationTools,
  type CanvasAnnotationToolsProps,
} from "@/lib/pdf-review/CanvasAnnotationTools";
import type { ReviewDocument } from "@/lib/pdf-review/types";
import styles from "@/lib/pdf-review/canvas.module.css";

interface CanvasDockProps extends CanvasAnnotationToolsProps {
  editing: boolean;
  documents: ReviewDocument[];
  activeId: string;
  page: number;
  total: number;
  scale: number;
  pan: boolean;
  onPanChange: (pan: boolean) => void;
  onNavigate: (documentId: string, page: number) => void;
  onZoom: (factor: number) => void;
  onFitAll: () => void;
  onFitPage: () => void;
  onAnnotate: () => void;
}

/** Screen-space controls stay outside the camera and its gesture listeners. */
export function CanvasDock({
  documents,
  activeId,
  page,
  total,
  scale,
  pan,
  onPanChange,
  onNavigate,
  onZoom,
  onFitAll,
  onFitPage,
  onAnnotate,
  editing,
  ...editingControls
}: CanvasDockProps) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const ui = useTranslations("chat.workspace");
  const [menu, setMenu] = useState<"document" | "zoom" | "annotation" | null>(
    null
  );
  const active = documents.find((document) => document.id === activeId);
  const annotationPanel = useRef<HTMLDivElement>(null);
  function closeWithEscape(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      setMenu(null);
    }
  }
  return (
    <div className={styles.dockOverlay}>
      <Section
        role="toolbar"
        tabIndex={-1}
        aria-label={ui("workspace")}
        flexDirection="row"
        width="fit"
        height="fit"
        padding={1.5}
        gap={1}
        className={styles.dock}
        onKeyDown={(event) => {
          if (
            !(event.target instanceof Node) ||
            !event.currentTarget.contains(event.target)
          )
            return;
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
            return;
          const controls = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(
              'button:not(:disabled), [role="button"][tabindex="0"]'
            )
          );
          const index = controls.findIndex(
            (control) => control === document.activeElement
          );
          if (index < 0) return;
          event.preventDefault();
          const next =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? controls.length - 1
                : (index +
                    (event.key === "ArrowRight" ? 1 : -1) +
                    controls.length) %
                  controls.length;
          controls[next]?.focus();
        }}
      >
        <Button
          size="sm"
          prominence={
            !pan && editingControls.tool === "select" ? "secondary" : "tertiary"
          }
          aria-pressed={!pan && editingControls.tool === "select"}
          icon={SvgCursor}
          aria-label={t("select")}
          tooltip={t("select")}
          onClick={() => onPanChange(false)}
        />
        <Button
          size="sm"
          prominence={pan ? "secondary" : "tertiary"}
          aria-pressed={pan}
          icon={SvgHand}
          aria-label={t("pan")}
          tooltip={t("pan")}
          onClick={() => onPanChange(true)}
        />
        <Popover
          open={menu === "annotation"}
          onOpenChange={(open) => {
            setMenu(open ? "annotation" : null);
            if (open) onAnnotate();
          }}
        >
          <Tooltip
            tooltip={ui("annotate")}
            suppressed={menu !== null}
            side="top"
          >
            <Popover.Trigger asChild>
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgEdit}
                aria-label={ui("annotate")}
                aria-pressed={editing}
              />
            </Popover.Trigger>
          </Tooltip>
          <Popover.Content
            onKeyDownCapture={closeWithEscape}
            side="top"
            sideOffset={12}
            width={60}
            ref={annotationPanel}
            tabIndex={-1}
            aria-label={ui("annotate")}
            onOpenAutoFocus={(event) => {
              event.preventDefault();
              annotationPanel.current?.focus();
            }}
          >
            <CanvasAnnotationTools
              {...editingControls}
              onToolChange={(next) => {
                editingControls.onToolChange(next);
                setMenu(null);
              }}
              onCorrect={
                editingControls.onCorrect
                  ? () => {
                      editingControls.onCorrect?.();
                      setMenu(null);
                    }
                  : undefined
              }
            />
          </Popover.Content>
        </Popover>
        <Divider orientation="vertical" />
        <Popover
          open={menu === "document"}
          onOpenChange={(open) => setMenu(open ? "document" : null)}
        >
          <Tooltip
            tooltip={active?.filename ?? t("documentControls")}
            suppressed={menu !== null}
            side="top"
          >
            <Popover.Trigger asChild>
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgFiles}
                rightIcon={SvgChevronDownSmall}
                aria-label={t("documentControls")}
              >
                {t("evidencePage", { page: Math.min(page, total) })}
              </Button>
            </Popover.Trigger>
          </Tooltip>
          <Popover.Content
            onKeyDownCapture={closeWithEscape}
            side="top"
            sideOffset={12}
            width={80}
          >
            <Section height="fit" alignItems="stretch" padding={1} gap={2}>
              <Text font="secondary-body" color="text-03">
                {t("documentControls")}
              </Text>
              {documents.map((document) => (
                <Button
                  key={document.id}
                  size="sm"
                  prominence={
                    document.id === activeId ? "secondary" : "tertiary"
                  }
                  aria-pressed={document.id === activeId}
                  tooltip={document.filename}
                  onClick={() => onNavigate(document.id, page)}
                >
                  {document.label}
                </Button>
              ))}
              <Divider />
              <Section flexDirection="row" height="fit" gap={1}>
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgChevronLeft}
                  aria-label={t("previous")}
                  tooltip={t("previous")}
                  disabled={page <= 1}
                  onClick={() => onNavigate(activeId, page - 1)}
                />
                <Section width={3} height="fit">
                  <InputTypeIn
                    type="number"
                    min={1}
                    max={total}
                    aria-label={t("page")}
                    value={String(Math.min(page, total))}
                    onChange={(event) => {
                      const next = Number(event.target.value);
                      if (Number.isInteger(next) && next >= 1 && next <= total)
                        onNavigate(activeId, next);
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
                  disabled={page >= total}
                  onClick={() => onNavigate(activeId, page + 1)}
                />
              </Section>
            </Section>
          </Popover.Content>
        </Popover>
        <Divider orientation="vertical" />
        <Popover
          open={menu === "zoom"}
          onOpenChange={(open) => setMenu(open ? "zoom" : null)}
        >
          <Tooltip
            tooltip={t("zoomControls")}
            suppressed={menu !== null}
            side="top"
          >
            <Popover.Trigger asChild>
              <Button
                size="sm"
                prominence="tertiary"
                rightIcon={SvgChevronDownSmall}
                aria-label={t("zoomControls")}
              >
                {t("zoom", { percent: Math.round(scale * 100) })}
              </Button>
            </Popover.Trigger>
          </Tooltip>
          <Popover.Content
            onKeyDownCapture={closeWithEscape}
            side="top"
            sideOffset={12}
            width={60}
          >
            <Section height="fit" alignItems="stretch" padding={1} gap={1}>
              <Section
                flexDirection="row"
                height="fit"
                justifyContent="between"
                gap={2}
              >
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgZoomOut}
                  aria-label={t("zoomOut")}
                  tooltip={t("zoomOut")}
                  onClick={() => onZoom(1 / 1.2)}
                />
                <Text font="secondary-body" color="text-03">
                  {t("zoom", { percent: Math.round(scale * 100) })}
                </Text>
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgZoomIn}
                  aria-label={t("zoomIn")}
                  tooltip={t("zoomIn")}
                  onClick={() => onZoom(1.2)}
                />
              </Section>
              <Divider />
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgFitWidth}
                onClick={() => {
                  onFitPage();
                  setMenu(null);
                }}
              >
                {t("fitPage")}
              </Button>
              {documents.length > 1 ? (
                <Button
                  size="sm"
                  prominence="tertiary"
                  icon={SvgFiles}
                  onClick={() => {
                    onFitAll();
                    setMenu(null);
                  }}
                >
                  {t("fitAll")}
                </Button>
              ) : null}
            </Section>
          </Popover.Content>
        </Popover>
      </Section>
    </div>
  );
}
