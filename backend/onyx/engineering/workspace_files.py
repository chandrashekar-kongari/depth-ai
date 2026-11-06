"""Authorized PDF sources and bounded region rendering."""

import hashlib
from io import BytesIO
from uuid import UUID

from pydantic import JsonValue
from pypdf import PdfReader
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.db.engineering_review import owned_review
from onyx.db.models import User
from onyx.db.user_file import get_file_id_by_user_file_id
from onyx.engineering.workspace_models import Anchor, PageGeometry, WorkspaceDocument
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store


def authorized_source(
    session: Session, user: User, reference: str
) -> tuple[bytes, str]:
    store = get_default_file_store()
    if "/" in reference:
        review_id, role = reference.split("/", 1)
        if role not in {"original", "revised"}:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing not found")
        try:
            review = owned_review(session, UUID(review_id), user.id)
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing not found") from error
        blob = review.original_blob if role == "original" else review.revised_blob
        name = review.original_name if role == "original" else review.revised_name
    else:
        blob = get_file_id_by_user_file_id(reference, session) or reference
        if not user_can_access_chat_file(blob, user, session):
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing not found")
        record = store.read_file_record(blob)
        if record is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Drawing not found")
        name = record.display_name or "drawing.pdf"
    with store.read_file(blob, mode="b") as source:
        data = source.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024 or not data.startswith(b"%PDF-"):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Use a PDF of at most 20 MiB")
    return data, name


def describe_pdf(data: bytes, reference: str, name: str) -> dict[str, JsonValue]:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
        raise ValueError("Use an unencrypted PDF with 1–100 pages")
    pages = []
    for page in reader.pages:
        crop = tuple(float(value) for value in page.cropbox)
        rotation = int(page.rotation) % 360
        width, height = crop[2] - crop[0], crop[3] - crop[1]
        if rotation in {90, 270}:
            width, height = height, width
        pages.append(
            PageGeometry(width=width, height=height, crop=crop, rotation=rotation)
        )
    return WorkspaceDocument(
        id=reference, name=name, sha256=hashlib.sha256(data).hexdigest(), pages=pages
    ).model_dump(mode="json")


def render_region(data: bytes, anchor: Anchor) -> bytes:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        sheet = pdf[anchor.page - 1]
        try:
            width, height = sheet.get_size()
            scale = min(3, 1600 / max(anchor.width * width, anchor.height * height))
            crop = (
                anchor.x * width,
                (1 - anchor.y - anchor.height) * height,
                (1 - anchor.x - anchor.width) * width,
                anchor.y * height,
            )
            bitmap = sheet.render(scale=scale, crop=crop)
            try:
                image = bitmap.to_pil()
                output = BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            sheet.close()
    finally:
        pdf.close()
