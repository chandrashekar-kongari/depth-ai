// Serve PDF.js support files from the same origin, pinned to the renderer version.
const { cpSync, mkdirSync } = require("node:fs");
const path = require("node:path");
const pdfjsRoot = path.dirname(require.resolve("pdfjs-dist/package.json"));
const pdfjsVersion = require("pdfjs-dist/package.json").version;
const pdfjsAssets = path.join(__dirname, "..", "public", "pdfjs", pdfjsVersion);
mkdirSync(pdfjsAssets, { recursive: true });
for (const directory of ["cmaps", "standard_fonts", "wasm", "iccs"]) {
  cpSync(path.join(pdfjsRoot, directory), path.join(pdfjsAssets, directory), {
    recursive: true,
  });
}
cpSync(
  path.join(pdfjsRoot, "build/pdf.worker.min.mjs"),
  path.join(pdfjsAssets, "pdf.worker.min.mjs")
);

// EmbedPDF runs without third-party runtime or font requests.
const engineRoot = path.dirname(require.resolve("@embedpdf/engines"));
const pdfiumRoot = path.dirname(require.resolve("@embedpdf/pdfium", { paths: [engineRoot] }));
const embedAssets = path.join(__dirname, "..", "public", "embedpdf", "2.15.1");
mkdirSync(embedAssets, { recursive: true });
cpSync(path.join(pdfiumRoot, "pdfium.wasm"), path.join(embedAssets, "pdfium.wasm"));
