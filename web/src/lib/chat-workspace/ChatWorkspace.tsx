"use client";

import "@/lib/chat-workspace/styles.css";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Group,
  Panel,
  Separator,
  useGroupRef,
  type Layout,
} from "react-resizable-panels";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Section } from "@opal/layouts";
import { useDrawingReviewLayout } from "@/app/app/message/messageComponents/renderers/drawingReviewLayout";

const DEFAULT_LAYOUT = { document: 65, conversation: 35 };
const STORAGE_KEY = "depth.chat.workspace.layout.v1";

/** Resizing and single-pane navigation keep both the editor and the draft mounted. */
export function ChatWorkspace({
  document,
  children,
}: {
  document: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("chat.workspace");
  const root = useRef<HTMLDivElement>(null);
  const group = useGroupRef();
  const saved = useRef<Layout>(DEFAULT_LAYOUT);
  const [compact, setCompact] = useState(false);
  const [pane, setPane] = useState("conversation");
  const { focusRequest } = useDrawingReviewLayout();
  const hasDocument = Boolean(document);

  useEffect(() => {
    try {
      const stored: unknown = JSON.parse(
        localStorage.getItem(STORAGE_KEY) ?? "null"
      );
      if (
        stored &&
        typeof stored === "object" &&
        "document" in stored &&
        "conversation" in stored &&
        typeof stored.document === "number" &&
        typeof stored.conversation === "number" &&
        Number.isFinite(stored.document) &&
        stored.document >= 20 &&
        stored.document <= 80 &&
        Math.abs(stored.document + stored.conversation - 100) < 0.1
      ) {
        saved.current = {
          document: stored.document,
          conversation: stored.conversation,
        };
        group.current?.setLayout(saved.current);
      }
    } catch {
      /* Storage can be disabled in private sessions. */
    }
    const element = root.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setCompact(entry.contentRect.width < 1000);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [group]);

  useEffect(() => {
    if (hasDocument && compact && focusRequest) setPane("document");
  }, [focusRequest, compact, hasDocument]);

  useEffect(() => {
    if (!hasDocument) {
      group.current?.setLayout({ document: 0, conversation: 100 });
      return;
    }
    group.current?.setLayout(
      compact
        ? {
            document: pane === "document" ? 100 : 0,
            conversation: pane === "conversation" ? 100 : 0,
          }
        : saved.current
    );
  }, [compact, pane, hasDocument, group]);

  return (
    <Section
      ref={root}
      data-depth-chat-workspace
      data-document-open={hasDocument}
      data-compact={compact}
      flexDirection="column"
      alignItems="stretch"
      justifyContent="start"
      gap={0}
      width="full"
      height="full"
      className="min-h-0 min-w-0 overflow-hidden bg-background-neutral-01"
    >
      {hasDocument && compact ? (
        <Section
          flexDirection="row"
          justifyContent="start"
          height="fit"
          padding={2}
          gap={1}
          className="shrink-0 border-b border-border-01"
        >
          <Button
            size="sm"
            prominence={pane === "conversation" ? "secondary" : "tertiary"}
            aria-pressed={pane === "conversation"}
            onClick={() => setPane("conversation")}
          >
            {t("conversation")}
          </Button>
          <Button
            size="sm"
            prominence={pane === "document" ? "secondary" : "tertiary"}
            aria-pressed={pane === "document"}
            onClick={() => setPane("document")}
          >
            {t("document")}
          </Button>
        </Section>
      ) : null}
      <Group
        groupRef={group}
        defaultLayout={
          hasDocument ? DEFAULT_LAYOUT : { document: 0, conversation: 100 }
        }
        disabled={compact || !hasDocument}
        className="min-h-0 flex-1"
        onLayoutChanged={(layout, meta) => {
          if (!hasDocument || compact || !meta.isUserInteraction) return;
          saved.current = layout;
          try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
          } catch {
            /* Optional preference. */
          }
        }}
      >
        <Panel
          id="document"
          defaultSize="65%"
          minSize={compact || !hasDocument ? 0 : 420}
          collapsible
          collapsedSize={0}
          className="min-h-0 min-w-0 overflow-hidden"
          inert={!hasDocument || (compact && pane !== "document")}
        >
          {document}
        </Panel>
        <Separator
          aria-label={t("resizePanels")}
          disabled={compact || !hasDocument}
          className={
            compact || !hasDocument ? "hidden" : "depth-workspace-separator"
          }
        />
        <Panel
          id="conversation"
          defaultSize="35%"
          minSize={compact || !hasDocument ? 0 : 360}
          collapsible
          collapsedSize={0}
          className="min-h-0 min-w-0 overflow-hidden"
          inert={hasDocument && compact && pane !== "conversation"}
        >
          {children}
        </Panel>
      </Group>
    </Section>
  );
}
