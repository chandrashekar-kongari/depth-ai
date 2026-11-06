import type { PDFDocumentProxy } from "pdfjs-dist";
import type { ReviewAnnotation } from "@/lib/pdf-review/annotations";

/** Flatten only the user's review layer onto a copy; uploaded bytes are never overwritten. */
export async function exportAnnotatedPdf(
  source: PDFDocumentProxy,
  annotations: ReviewAnnotation[]
): Promise<Uint8Array> {
  const { PDFDocument, rgb, degrees } = await import("pdf-lib");
  const output = await PDFDocument.load(await source.getData());
  for (const annotation of annotations) {
    const page = output.getPage(annotation.page - 1);
    const sourcePage = await source.getPage(annotation.page);
    const viewport = sourcePage.getViewport({ scale: 1 });
    const points = annotation.points.map((point) => {
      const converted = viewport.convertToPdfPoint(
        point.x * viewport.width,
        point.y * viewport.height
      );
      return { x: converted[0] ?? 0, y: converted[1] ?? 0 };
    });
    const start = points[0];
    if (!start) continue;
    if (annotation.kind === "highlight") {
      const end = annotation.points.at(-1);
      const first = annotation.points[0];
      if (!end || !first) continue;
      const corners = [
        [first.x, first.y],
        [end.x, first.y],
        [end.x, end.y],
        [first.x, end.y],
      ].map(([x = 0, y = 0]) =>
        viewport.convertToPdfPoint(x * viewport.width, y * viewport.height)
      );
      // drawSvgPath flips its y axis; negate PDF y to preserve viewport mapping, including rotated/cropped pages.
      const path =
        corners
          .map(
            (point, index) =>
              `${index ? "L" : "M"} ${point[0] ?? 0} ${-(point[1] ?? 0)}`
          )
          .join(" ") + " Z";
      page.drawSvgPath(path, { color: rgb(1, 0.8, 0), opacity: 0.3 });
    } else if (annotation.kind === "ink") {
      points.slice(1).forEach((end, index) => {
        const begin = points[index];
        if (begin)
          page.drawLine({
            start: begin,
            end,
            thickness: viewport.width * 0.0025,
            color: rgb(0.85, 0.15, 0.15),
          });
      });
    } else {
      // Browser text rendering preserves Unicode without shipping private notes to a font service.
      const canvas = document.createElement("canvas");
      canvas.width = 720;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("canvas");
      context.font = "24px sans-serif";
      const lines: string[] = [];
      let line = "";
      for (const character of annotation.text) {
        if (
          character === "\n" ||
          context.measureText(line + character).width > 672
        ) {
          lines.push(line);
          line = character === "\n" ? "" : character;
        } else line += character;
      }
      lines.push(line);
      canvas.height = 48 + lines.length * 32;
      context.fillStyle = "#fff1a8";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#242424";
      context.font = "24px sans-serif";
      lines.forEach((text, index) =>
        context.fillText(text, 24, 36 + index * 32)
      );
      const first = annotation.points[0];
      if (!first) continue;
      const width = Math.min(
        viewport.width * 0.3,
        viewport.width * (1 - first.x)
      );
      const height = Math.min(
        (width * canvas.height) / canvas.width,
        viewport.height * (1 - first.y)
      );
      const origin = viewport.convertToPdfPoint(
        first.x * viewport.width,
        first.y * viewport.height + height
      );
      const right = viewport.convertToPdfPoint(
        first.x * viewport.width + 1,
        first.y * viewport.height + height
      );
      const image = await output.embedPng(canvas.toDataURL("image/png"));
      page.drawImage(image, {
        x: origin[0] ?? 0,
        y: origin[1] ?? 0,
        width,
        height,
        rotate: degrees(
          (Math.atan2(
            (right[1] ?? 0) - (origin[1] ?? 0),
            (right[0] ?? 0) - (origin[0] ?? 0)
          ) *
            180) /
            Math.PI
        ),
      });
    }
  }
  return output.save();
}
