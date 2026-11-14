"use client";

import React, { useMemo, useRef, useState } from "react";
import "@/app/css/recent-files.css";
import { useTranslations } from "next-intl";
import {
  Text,
  Button,
  Dropdown,
  LineItemButton,
  type DropdownVirtualAnchor,
  type DropdownMenuItem,
  type DropdownMenuRow,
  type DropdownRowProps,
} from "@opal/components";
import { noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
import { ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { isFilePending } from "@/lib/projects/utils";
import { Hoverable } from "@opal/core";
import { useProjectsContext } from "@/lib/projects/providers";
import { MAX_FILES_TO_SHOW } from "@/lib/constants";
import { isImageFile } from "@/lib/utils";
import {
  SvgExternalLink,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgMoreHorizontal,
  SvgPaperclip,
  SvgCheck,
} from "@opal/icons";
const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

interface FileLineItemProps {
  projectFile: ProjectFile;
  highlighted: boolean;
  selected?: boolean;
  /** The row props from the list: the id, role, stop and click handling. */
  rowProps: DropdownRowProps;
  onFileClick: (file: ProjectFile) => void;
}

/** A recent file: a presentational row whose end control views the file. */
function FileLineItem({
  projectFile,
  highlighted,
  selected,
  rowProps,
  onFileClick,
}: FileLineItemProps) {
  const t = useTranslations("common.filePicker");
  const showLoader = useMemo(
    () =>
      isFilePending(projectFile.status) ||
      projectFile.status === UserFileStatus.DELETING,
    [projectFile.status]
  );

  const disableActionButton = useMemo(
    () =>
      String(projectFile.status) === UserFileStatus.UPLOADING ||
      String(projectFile.status) === UserFileStatus.DELETING,
    [projectFile.status]
  );

  return (
    <Hoverable.Root group="FileLineItem">
      <LineItemButton
        presentational
        data-recent-file-row
        selectVariant="select-heavy"
        interaction={highlighted ? "hover" : "rest"}
        sizePreset="secondary"
        variant="section"
        padding={0}
        rounding={2}
        icon={
          selected
            ? SvgCheck
            : showLoader
              ? ({ className }) => (
                  <SvgLoader className={cn(className, "animate-spin")} />
                )
              : isImageFile(projectFile.name)
                ? SvgImage
                : SvgFileText
        }
        rightChildren={
          <div className="recent-file-preview-slot">
            <Hoverable.Item
              group="FileLineItem"
              variant="replace-on-hover"
              resting={
                <Text as="p" font="secondary-body" color="text-03" maxLines={1}>
                  {getFileExtension(projectFile.name)}
                </Text>
              }
            >
              <Button
                icon={SvgExternalLink}
                onClick={noProp(() => onFileClick(projectFile))}
                tooltip={t("viewFileButton.tooltip")}
                disabled={disableActionButton}
                prominence="internal"
                size="sm"
              />
            </Hoverable.Item>
          </div>
        }
        title={projectFile.name}
        titleMaxLines={1}
        {...rowProps}
      />
    </Hoverable.Root>
  );
}

interface FilePickerItemsProps {
  recentFiles: ProjectFile[];
  onPickRecent: (file: ProjectFile) => void;
  onFileClick: (file: ProjectFile) => void;
  triggerUploadPicker: () => void;
  visibleCount: number;
  loadMore: () => void;
  selectedFileIds?: string[];
}

/**
 * The rows: upload, then the "quick" recent files (speed dial, for files)
 * under a title, and a row to the rest when there are more.
 */
function useFilePickerItems({
  recentFiles,
  onPickRecent,
  onFileClick,
  triggerUploadPicker,
  visibleCount,
  loadMore,
  selectedFileIds,
}: FilePickerItemsProps): DropdownMenuItem[] {
  const t = useTranslations("common.filePicker");
  const hasFiles = recentFiles.length > 0;
  const shouldShowMoreFilesButton = recentFiles.length > visibleCount;
  const quickAccessFiles = recentFiles.slice(0, visibleCount);

  const fileRows: DropdownMenuRow[] = [
    ...quickAccessFiles.map(
      (projectFile): DropdownMenuRow => ({
        kind: "custom",
        id: `file-${projectFile.id}`,
        keywords: [projectFile.name],
        onActivate: () => onPickRecent(projectFile),
        // ArrowRight reaches the row's view control.
        onSecondary: () => onFileClick(projectFile),
        render: ({ highlighted, props }) => (
          <FileLineItem
            projectFile={projectFile}
            selected={selectedFileIds?.includes(projectFile.id)}
            highlighted={highlighted}
            rowProps={props}
            onFileClick={onFileClick}
          />
        ),
      })
    ),
    ...(shouldShowMoreFilesButton
      ? [
          {
            kind: "action" as const,
            id: "more-files",
            icon: SvgMoreHorizontal,
            title: t("allRecentFilesButton.title"),
            keepOpen: true,
            onSelect: loadMore,
          },
        ]
      : []),
  ];

  return [
    {
      kind: "custom",
      id: "upload-files",
      keywords: [t("uploadFiles.title")],
      onActivate: triggerUploadPicker,
      render: ({ highlighted, props }) => (
        <LineItemButton
          {...props}
          presentational
          data-attachment-upload
          icon={SvgPaperclip}
          title={t("uploadFiles.title")}
          titleMaxLines={1}
          sizePreset="secondary"
          variant="section"
          interaction={highlighted ? "hover" : "rest"}
          rounding={2}
          padding={0}
          rightChildren={
            <Text font="secondary-body" color="text-03" maxLines={1}>
              {t("uploadFiles.description")}
            </Text>
          }
        />
      ),
    },
    ...(hasFiles
      ? [
          {
            kind: "group" as const,
            title: t("recentFiles.title"),
            items: fileRows,
          },
        ]
      : []),
  ];
}

export interface FilePickerPopoverProps {
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  handleUploadChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  trigger?: React.ReactNode | ((open: boolean) => React.ReactNode);
  selectedFileIds?: string[];
  anchorRef?: React.RefObject<HTMLElement | null>;
}

export default function FilePickerPopover({
  onPickRecent,
  onUnpickRecent,
  onFileClick,
  handleUploadChange,
  trigger,
  selectedFileIds,
  anchorRef,
}: FilePickerPopoverProps) {
  const t = useTranslations("common.filePicker");
  const { allRecentFiles } = useProjectsContext();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [visibleCount, setVisibleCount] = useState(MAX_FILES_TO_SHOW);
  const anchor = useMemo<DropdownVirtualAnchor | undefined>(() => {
    const element = anchorRef?.current;
    if (!open || !element) return undefined;
    return {
      contextElement: element,
      getBoundingClientRect: () => element.getBoundingClientRect(),
    };
  }, [anchorRef, open]);
  const items = useFilePickerItems({
    recentFiles: allRecentFiles,
    selectedFileIds,
    visibleCount,
    loadMore: () => setVisibleCount((count) => count + 10),
    onPickRecent: (file) => {
      if (selectedFileIds?.includes(file.id)) onUnpickRecent?.(file);
      else onPickRecent?.(file);
    },
    onFileClick: (file) => {
      onFileClick?.(file);
      setOpen(false);
    },
    triggerUploadPicker: () => fileInputRef.current?.click(),
  });

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        multiple
        onChange={handleUploadChange}
        accept={"*/*"}
      />

      <Dropdown
        width={anchorRef ? undefined : 80}
        virtualAnchor={anchor}
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen) setVisibleCount(MAX_FILES_TO_SHOW);
        }}
      >
        <Dropdown.Trigger asChild>
          {typeof trigger === "function" ? trigger(open) : trigger}
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("uploadFiles.title")}
          items={items}
          sizePreset="secondary"
        />
      </Dropdown>
    </>
  );
}
