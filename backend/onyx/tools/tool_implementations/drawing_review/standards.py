"""Company standards for a drawing review.

Standards come from the agent document sets. This module does not store them.
"""

from __future__ import annotations

from dataclasses import dataclass

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.context.search.models import ChunkSearchRequest, PersonaSearchInfo
from onyx.context.search.pipeline import search_pipeline
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.document_index.interfaces import DocumentIndex
from onyx.utils.logger import setup_logger

logger = setup_logger()

NO_COMPANY_STANDARD = "No company standard was used."

_QUERIES = (
    "engineering drawing title block requirements",
    "geometric dimensioning and tolerancing drawing rules",
    "dimension tolerance limits machined parts",
    "bill of materials material callout drawing",
)
_CHUNK_LIMIT = 2
_MAX_EXCERPTS = 4
_EXCERPT_CHARS = 400


@dataclass(frozen=True)
class StandardExcerpt:
    title: str
    text: str


def has_company_standards(persona_search_info: PersonaSearchInfo | None) -> bool:
    if persona_search_info is None:
        return False
    return bool(
        persona_search_info.document_set_names
        or persona_search_info.attached_document_ids
        or persona_search_info.hierarchy_node_ids
    )


def retrieve_drawing_standards(
    user: User | None,
    persona_search_info: PersonaSearchInfo | None,
    document_index: DocumentIndex | None,
) -> list[StandardExcerpt]:
    """Return a few chunks from the agent knowledge. An empty list means none."""
    if (
        user is None
        or document_index is None
        or DISABLE_VECTOR_DB
        or not has_company_standards(persona_search_info)
    ):
        return []

    excerpts: list[StandardExcerpt] = []
    seen: set[str] = set()
    try:
        with get_session_with_current_tenant() as db_session:
            for query in _QUERIES:
                chunks = search_pipeline(
                    chunk_search_request=ChunkSearchRequest(
                        query=query, limit=_CHUNK_LIMIT
                    ),
                    document_index=document_index,
                    user=user,
                    persona_search_info=persona_search_info,
                    db_session=db_session,
                )
                for chunk in chunks:
                    if chunk.document_id in seen:
                        continue
                    seen.add(chunk.document_id)
                    title = (
                        chunk.semantic_identifier or chunk.title or "Standard"
                    ).strip()
                    text = " ".join(chunk.content.split())
                    if not title or not text:
                        continue
                    excerpts.append(
                        StandardExcerpt(title=title[:120], text=text[:_EXCERPT_CHARS])
                    )
                    if len(excerpts) >= _MAX_EXCERPTS:
                        return excerpts
    except Exception:
        logger.warning("Drawing review could not retrieve standards", exc_info=True)
        return []
    return excerpts
