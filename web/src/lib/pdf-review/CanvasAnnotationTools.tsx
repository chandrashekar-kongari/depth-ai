"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { PdfAnnotationObject } from "@embedpdf/models";
import { Button, Divider, InputTypeIn, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  SvgDownload,
  SvgTrash,
  SvgCursor,
  SvgPaintBrush,
  SvgPenSmall,
  SvgSquare,
  SvgCircle,
  SvgArrowUpRight,
  SvgTextLines,
  SvgBubbleText,
  SvgTextLinesSmall,
  SvgSlash,
  SvgRevert,
  SvgRefreshCw,
  SvgPin,
  SvgFileText,
} from "@opal/icons";

export interface CanvasAnnotationToolsProps {
  tool: string;
  editable: boolean;
  pending: number;
  canUndo: boolean;
  canRedo: boolean;
  selected: PdfAnnotationObject | null;
  onToolChange: (tool: string) => void;
  onUndo: () => void;
  onRedo: () => void;
  onDelete: () => void;
  onNoteChange: (contents: string) => void;
  onExport: () => void;
  onPrint: () => void;
  onCorrect?: () => void;
  status: string;
  onRetry: () => void;
  hasError: boolean;
}

export function CanvasAnnotationTools({
  tool,
  editable,
  pending,
  canUndo,
  canRedo,
  selected,
  onToolChange,
  onUndo,
  onRedo,
  onDelete,
  onNoteChange,
  onExport,
  onPrint,
  onCorrect,
  status,
  onRetry,
  hasError,
}: CanvasAnnotationToolsProps) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const [contents, setContents] = useState("");
  useEffect(
    () => setContents(selected?.contents ?? ""),
    [selected?.id, selected?.contents]
  );
  return (
    <Section height="fit" alignItems="stretch" padding={1} gap={2}>
      <Text font="secondary-body" color="text-03">
        {t("tools")}
      </Text>
      <Section
        flexDirection="row"
        height="fit"
        gap={1}
        wrap
        justifyContent="start"
      >
        {[
          { id: "select", label: t("select"), icon: SvgCursor },
          { id: "ink", label: t("ink"), icon: SvgPenSmall },
          { id: "square", label: t("rectangle"), icon: SvgSquare },
          { id: "circle", label: t("ellipse"), icon: SvgCircle },
          { id: "lineArrow", label: t("arrow"), icon: SvgArrowUpRight },
          { id: "freeText", label: t("freeText"), icon: SvgTextLines },
          { id: "textComment", label: t("note"), icon: SvgBubbleText },
          { id: "highlight", label: t("highlight"), icon: SvgPaintBrush },
          {
            id: "inkHighlighter",
            label: t("inkHighlighter"),
            icon: SvgPaintBrush,
          },
          { id: "freeTextCallout", label: t("callout"), icon: SvgBubbleText },
          { id: "underline", label: t("underline"), icon: SvgTextLinesSmall },
          { id: "strikeout", label: t("strikeout"), icon: SvgSlash },
        ].map((item) => (
          <Section key={item.id} width={2} height="fit">
            <Button
              size="md"
              icon={item.icon}
              aria-label={item.label}
              tooltip={item.label}
              aria-pressed={tool === item.id}
              prominence={tool === item.id ? "secondary" : "tertiary"}
              disabled={!editable}
              onClick={() => onToolChange(item.id)}
            />
          </Section>
        ))}
      </Section>
      <Divider />
      <Section
        flexDirection="row"
        height="fit"
        gap={1}
        justifyContent="between"
      >
        <Section flexDirection="row" width="fit" height="fit" gap={1}>
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgRevert}
            aria-label={t("undo")}
            tooltip={t("undo")}
            disabled={!editable || !!pending || !canUndo}
            onClick={onUndo}
          />
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgRefreshCw}
            aria-label={t("redo")}
            tooltip={t("redo")}
            disabled={!editable || !!pending || !canRedo}
            onClick={onRedo}
          />
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgTrash}
            aria-label={t("delete")}
            tooltip={t("delete")}
            disabled={!editable || !selected}
            onClick={onDelete}
          />
        </Section>
        {onCorrect ? (
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgPin}
            aria-label={t("correctLocation")}
            tooltip={t("correctLocation")}
            disabled={!editable || !!pending}
            onClick={onCorrect}
          />
        ) : null}
      </Section>
      {selected ? (
        <>
          <InputTypeIn
            aria-label={t("noteText")}
            value={contents}
            maxLength={10000}
            onChange={(event) => setContents(event.target.value)}
          />
          <Button
            size="sm"
            disabled={!editable}
            onClick={() => onNoteChange(contents)}
          >
            {t("saveNote")}
          </Button>
        </>
      ) : null}
      <Divider />
      <Section
        flexDirection="row"
        height="fit"
        gap={1}
        justifyContent="between"
      >
        <Section flexDirection="row" width="fit" height="fit" gap={1}>
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgDownload}
            aria-label={t("export")}
            tooltip={t("export")}
            disabled={!editable || !!pending}
            onClick={onExport}
          />
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgFileText}
            aria-label={t("print")}
            tooltip={t("print")}
            disabled={!editable || !!pending}
            onClick={onPrint}
          />
        </Section>
      </Section>
      <Text font="secondary-body" color="text-03">
        {status}
      </Text>
      {hasError ? (
        <Button size="sm" prominence="tertiary" onClick={onRetry}>
          {t("retry")}
        </Button>
      ) : null}
    </Section>
  );
}
