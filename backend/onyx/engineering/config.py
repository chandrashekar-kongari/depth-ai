"""Review inference is explicit and independent of chat defaults."""

import ipaddress
import os
from urllib.parse import urlsplit

from onyx.llm.factory import get_llm
from onyx.llm.interfaces import LLM

REVIEW_MODEL = os.getenv("DEPTH_REVIEW_MODEL", "")
REVIEW_API_BASE = os.getenv("DEPTH_REVIEW_API_BASE", "")
REVIEW_ENABLED = os.getenv("DEPTH_REVIEW_ENABLED", "false").lower() == "true"
MAX_PDF_BYTES = 20 * 1024 * 1024
REVIEW_CONTEXT_TOKENS = 8192


def validate_private_endpoint(url: str) -> str:
    """Use literal internal IPs to avoid DNS rebinding and public fallback."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Review endpoint must be an internal HTTP(S) origin")
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        _ = parsed.port
    except ValueError as error:
        raise ValueError(
            "Review endpoint requires a literal private or loopback IP address"
        ) from error
    if (
        not (address.is_private or address.is_loopback)
        or address.is_unspecified
        or address.is_multicast
        or address.is_link_local
    ):
        raise ValueError("Review endpoint must use a private or loopback IP address")
    return url.rstrip("/")


def private_review_llm() -> LLM | None:
    if not REVIEW_MODEL or not REVIEW_API_BASE:
        return None
    endpoint = validate_private_endpoint(REVIEW_API_BASE)
    return get_llm(
        provider="ollama_chat",
        model=REVIEW_MODEL,
        api_base=endpoint,
        deployment_name=None,
        api_key=None,
        max_input_tokens=REVIEW_CONTEXT_TOKENS,
        model_kwargs={"num_ctx": REVIEW_CONTEXT_TOKENS},
        temperature=0,
        supports_images=True,
    )
