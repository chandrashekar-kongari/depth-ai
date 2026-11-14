"""Find and render close-ups of likely colored markup on an original PDF page."""

from contextlib import closing
from dataclasses import dataclass
from io import BytesIO

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from onyx.tools.models import DrawingMarkBox

_MAX_CROPS = 4
_MAX_SEARCH_SIDE = 2400
_MAX_CROP_SIDE = 1200


@dataclass(frozen=True)
class MarkupCrop:
    box: DrawingMarkBox
    image: bytes


def markup_regions(
    image: Image.Image, *, limit: int = _MAX_CROPS, padding: bool = True
) -> list[DrawingMarkBox]:
    preview = image.copy()
    preview.thumbnail((_MAX_SEARCH_SIDE, _MAX_SEARCH_SIDE))
    rgb = np.asarray(preview.convert("RGB"))
    height, width = rgb.shape[:2]

    # Neutral drawing lines disappear from the mask. Color is only a search cue.
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    ink = (chroma >= 45).astype(np.uint8)
    join = max(3, round(min(width, height) * 0.018))
    grouped = cv2.dilate(ink, np.ones((join, join), dtype=np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(grouped)
    regions: list[tuple[int, int, int, int, int]] = []
    for index, (x, y, w, h, _) in enumerate(stats[1:], 1):
        if w * h > width * height * 0.16:
            continue
        pixels = np.count_nonzero(
            ink[y : y + h, x : x + w] & (labels[y : y + h, x : x + w] == index)
        )
        if pixels >= 8:
            regions.append((int(pixels), int(x), int(y), int(w), int(h)))

    boxes: list[DrawingMarkBox] = []
    for _, x, y, w, h in sorted(regions, reverse=True)[:limit]:
        pad = max(join, round(max(w, h) * 0.35)) if padding else 0
        left, top = max(0, x - pad) / width, max(0, y - pad) / height
        right, bottom = (
            min(width, x + w + pad) / width,
            min(height, y + h + pad) / height,
        )
        boxes.append(
            DrawingMarkBox(x=left, y=top, width=right - left, height=bottom - top)
        )
    return boxes


def render_markup_crops(
    pdf_bytes: bytes, page_number: int, overview: bytes
) -> list[MarkupCrop]:
    """Run in an isolated process. Page numbers are one-based."""
    with Image.open(BytesIO(overview)) as image:
        boxes = markup_regions(image)
    if not boxes:
        return []
    crops: list[MarkupCrop] = []
    with pdfium.PdfDocument(pdf_bytes) as document:
        with closing(document[page_number - 1]) as page:
            page_width, page_height = page.get_size()
            for box in boxes:
                left, top = box.x, box.y
                right, bottom = left + box.width, top + box.height
                scale = min(
                    4.0,
                    _MAX_CROP_SIDE
                    / max(box.width * page_width, box.height * page_height),
                )
                # PDFium crops the rendered view in left, bottom, right, top order.
                with closing(
                    page.render(
                        scale=scale,
                        crop=(
                            left * page_width,
                            (1 - bottom) * page_height,
                            (1 - right) * page_width,
                            top * page_height,
                        ),
                        limit_image_cache=True,
                        draw_annots=True,
                    )
                ) as bitmap:
                    buffer = BytesIO()
                    bitmap.to_pil().save(buffer, format="PNG")
                crops.append(MarkupCrop(box, buffer.getvalue()))
    return crops
