"""Recover parseable working bytes for a review while preserving the source PDF."""

from contextlib import closing
from io import BytesIO

import pypdfium2 as pdfium
from pypdfium2 import raw

_MAX_RECOVERY_BYTES = 20 * 1024 * 1024
_MAX_RECOVERY_PIXELS = 4_000_000


def recover_review_pdf(data: bytes, max_pages: int) -> bytes:
    if len(data) > _MAX_RECOVERY_BYTES:
        raise ValueError("PDF is too large for parser recovery.")
    with pdfium.PdfDocument(data) as source, pdfium.PdfDocument.new() as copy:
        if raw.FPDF_GetSecurityHandlerRevision(source.raw) != -1:
            raise ValueError("Encrypted PDF cannot be recovered.")
        if not 1 <= len(source) <= max_pages:
            raise ValueError("PDF page count exceeds the recovery limit.")
        copy.import_pages(source)
        output = BytesIO()
        copy.save(output)
        recovered = output.getvalue()
        if len(recovered) > _MAX_RECOVERY_BYTES:
            raise ValueError("Recovered PDF is too large.")
        with pdfium.PdfDocument(recovered) as reopened:
            if len(source) != len(reopened):
                raise ValueError("PDF recovery changed the page count.")
            for index in range(len(source)):
                with (
                    closing(source[index]) as before,
                    closing(reopened[index]) as after,
                ):
                    _check_recovered_page(before, after)
    return recovered


def _check_recovered_page(before: pdfium.PdfPage, after: pdfium.PdfPage) -> None:
    width, height = before.get_size()
    if (
        width * height > _MAX_RECOVERY_PIXELS
        or before.get_size() != after.get_size()
        or before.get_bbox() != after.get_bbox()
        or before.get_rotation() != after.get_rotation()
        or raw.FPDFPage_GetAnnotCount(before.raw)
        != raw.FPDFPage_GetAnnotCount(after.raw)
    ):
        raise ValueError("PDF recovery could not preserve the page or its annotations.")
    with (
        closing(before.get_textpage()) as original_text,
        closing(after.get_textpage()) as recovered_text,
        closing(before.render(draw_annots=True)) as original_image,
        closing(after.render(draw_annots=True)) as recovered_image,
    ):
        if original_text.get_text_range() != recovered_text.get_text_range() or bytes(
            original_image.buffer
        ) != bytes(recovered_image.buffer):
            raise ValueError("PDF recovery changed the page text or appearance.")
