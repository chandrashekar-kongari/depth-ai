"use client";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { PdfCanvas } from "@/lib/pdf-review/PdfCanvas";
import { PdfEngineProvider } from "@/lib/pdf-review/embedpdf/provider";
import type { PdfReviewWorkspaceProps } from "@/lib/pdf-review/types";

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
      <PdfCanvas {...props} />
    </PdfEngineProvider>
  );
}
