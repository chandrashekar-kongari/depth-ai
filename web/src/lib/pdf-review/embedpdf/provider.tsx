"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { z } from "zod";
import { createPluginRegistration } from "@embedpdf/core";
import { EmbedPDF } from "@embedpdf/core/react";
import { usePdfiumEngine } from "@embedpdf/engines/react";
import { DocumentManagerPluginPackage } from "@embedpdf/plugin-document-manager/react";
import { ViewportPluginPackage } from "@embedpdf/plugin-viewport/react";
import { ScrollPluginPackage } from "@embedpdf/plugin-scroll/react";
import { RenderPluginPackage } from "@embedpdf/plugin-render/react";
import { TilingPluginPackage } from "@embedpdf/plugin-tiling/react";
import { ZoomPluginPackage, ZoomMode } from "@embedpdf/plugin-zoom/react";
import { PanPluginPackage } from "@embedpdf/plugin-pan/react";
import { RotatePluginPackage } from "@embedpdf/plugin-rotate/react";
import { SelectionPluginPackage } from "@embedpdf/plugin-selection/react";
import { AnnotationPluginPackage } from "@embedpdf/plugin-annotation/react";
import { HistoryPluginPackage } from "@embedpdf/plugin-history/react";
import { InteractionManagerPluginPackage } from "@embedpdf/plugin-interaction-manager/react";
import { SearchPluginPackage } from "@embedpdf/plugin-search/react";
import { ExportPluginPackage } from "@embedpdf/plugin-export/react";
import { ThumbnailPluginPackage } from "@embedpdf/plugin-thumbnail/react";
import { PrintPluginPackage } from "@embedpdf/plugin-print/react";
import { Text } from "@opal/components";
import { useTranslations } from "next-intl";
import type { ReviewDocument } from "@/lib/pdf-review/types";

interface PdfEngineProviderProps {
  documents: ReviewDocument[];
  children: ReactNode;
}

export function PdfEngineProvider(props: PdfEngineProviderProps) {
  const [origin, setOrigin] = useState<string | null>(null);
  const t = useTranslations("chat.messages.pdfWorkspace");
  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);
  if (!origin)
    return (
      <Text font="secondary-body" color="text-03">
        {t("loading")}
      </Text>
    );
  return <ClientPdfEngineProvider {...props} origin={origin} />;
}

function ClientPdfEngineProvider({
  documents,
  children,
  origin,
}: PdfEngineProviderProps & { origin: string }) {
  const t = useTranslations("chat.messages.pdfWorkspace");
  const { engine, error } = usePdfiumEngine({
    wasmUrl: new URL("/embedpdf/2.15.1/pdfium.wasm", origin).href,
    worker: true,
    fontFallback: null,
  });
  const source = JSON.stringify(
    documents.map((document) => ({
      documentId: document.id,
      url: new URL(document.url, origin).href,
      autoActivate: document.id === documents[0]?.id,
      name: document.filename,
    }))
  );
  const plugins = useMemo(
    () => [
      createPluginRegistration(DocumentManagerPluginPackage, {
        initialDocuments: z
          .array(
            z.object({
              documentId: z.string(),
              url: z.string(),
              name: z.string(),
              autoActivate: z.boolean(),
            })
          )
          .parse(JSON.parse(source)),
        maxDocuments: 2,
      }),
      createPluginRegistration(ViewportPluginPackage),
      createPluginRegistration(ScrollPluginPackage, {
        defaultPageGap: 24,
        defaultBufferSize: 0,
      }),
      createPluginRegistration(RenderPluginPackage, { withAnnotations: false }),
      createPluginRegistration(TilingPluginPackage, { tileSize: 768 }),
      createPluginRegistration(ZoomPluginPackage, {
        defaultZoomLevel: ZoomMode.FitPage,
      }),
      createPluginRegistration(PanPluginPackage),
      createPluginRegistration(RotatePluginPackage),
      createPluginRegistration(InteractionManagerPluginPackage),
      createPluginRegistration(SelectionPluginPackage),
      createPluginRegistration(HistoryPluginPackage),
      createPluginRegistration(AnnotationPluginPackage, {
        autoOpenLinks: false,
        tools: [
          { id: "freeText", defaults: { contents: t("note") } },
          { id: "textComment", defaults: { contents: t("note") } },
        ],
      }),
      createPluginRegistration(SearchPluginPackage),
      createPluginRegistration(ExportPluginPackage),
      createPluginRegistration(ThumbnailPluginPackage),
      createPluginRegistration(PrintPluginPackage),
    ],
    [source, t]
  );
  if (!engine)
    return (
      <Text font="secondary-body" color="text-03">
        {t(error ? "loadFailed" : "loading")}
      </Text>
    );
  return (
    <EmbedPDF engine={engine} plugins={plugins}>
      {children}
    </EmbedPDF>
  );
}
