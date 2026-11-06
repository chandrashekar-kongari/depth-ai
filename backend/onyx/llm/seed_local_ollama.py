"""Seed one local Ollama provider when a deployment has no chat model yet.

The offline desktop sets ``ONYX_SEED_OLLAMA_API_BASE`` and
``ONYX_SEED_OLLAMA_MODEL`` before the API starts. There is no admin user on
a fresh database, so this uses the same write path as the admin provider API
(``upsert_llm_provider`` and ``update_default_model``) instead of HTTP.
"""

import time

import httpx
from sqlalchemy.orm import Session

from onyx.configs.model_configs import (
    ONYX_SEED_OLLAMA_API_BASE,
    ONYX_SEED_OLLAMA_EXTRA_MODELS,
    ONYX_SEED_OLLAMA_MODEL,
)
from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    fetch_default_model,
    fetch_existing_llm_provider,
    update_default_model,
    upsert_llm_provider,
)
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from onyx.server.manage.llm.utils import generate_ollama_display_name
from onyx.utils.logger import setup_logger

logger = setup_logger()

LOCAL_OLLAMA_PROVIDER_NAME = "Ollama"
# First look is immediate. Eleven more tries, five seconds apart, is about a minute.
SEED_LIST_ATTEMPTS = 12
SEED_LIST_INTERVAL_SECONDS = 5


def ollama_model_names(api_base: str) -> set[str]:
    """Names currently served by an Ollama ``/api/tags`` endpoint."""
    url = f"{api_base.rstrip('/')}/api/tags"
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models", [])
    if not isinstance(models, list):
        return set()
    names: set[str] = set()
    for model in models:
        if isinstance(model, dict):
            name = model.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names


def extra_model_names(raw: str, primary: str) -> tuple[str, ...]:
    """Model names from a comma-separated env value, without the chat default."""
    names: list[str] = []
    seen = {primary}
    for part in raw.split(","):
        name = part.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return tuple(names)


def build_ollama_seed_request(
    *,
    api_base: str,
    model_names: list[str],
    existing_id: int | None,
    keep_existing_models: bool = False,
) -> LLMProviderUpsertRequest:
    """The provider write the admin API would send for these local models."""
    return LLMProviderUpsertRequest(
        id=existing_id,
        name=LOCAL_OLLAMA_PROVIDER_NAME,
        provider=LlmProviderNames.OLLAMA_CHAT,
        api_base=api_base,
        api_key=None,
        api_key_changed=True,
        is_public=True,
        keep_existing_models=keep_existing_models,
        model_configurations=[
            ModelConfigurationUpsertRequest(
                name=model_name,
                is_visible=True,
                supports_chat=True,
                display_name=generate_ollama_display_name(model_name),
            )
            for model_name in model_names
        ],
    )


def _wait_for_named_model(api_base: str, model_name: str) -> set[str] | None:
    """The Ollama tag list once it contains ``model_name``.

    Returns ``None`` when that model never appears. Does not accept a different model.
    """
    last_error: Exception | None = None
    saw_list = False
    for attempt in range(SEED_LIST_ATTEMPTS):
        if attempt > 0:
            time.sleep(SEED_LIST_INTERVAL_SECONDS)
        try:
            names = ollama_model_names(api_base)
        except Exception as error:
            last_error = error
            continue
        saw_list = True
        if model_name in names:
            return names
    if saw_list:
        logger.warning(
            "Skipping local Ollama seed; %s is not served at %s",
            model_name,
            api_base,
        )
    else:
        logger.warning(
            "Skipping local Ollama seed; could not list models at %s: %s",
            api_base,
            last_error,
        )
    return None


def _listed_model_names(api_base: str) -> set[str] | None:
    try:
        return ollama_model_names(api_base)
    except Exception as error:
        logger.warning(
            "Skipping extra Ollama models; could not list models at %s: %s",
            api_base,
            error,
        )
        return None


def _write_provider(
    db_session: Session,
    api_base: str,
    model_names: list[str],
    *,
    existing_id: int | None,
    keep_existing_models: bool,
    chat_default: str | None,
) -> bool:
    request = build_ollama_seed_request(
        api_base=api_base,
        model_names=model_names,
        existing_id=existing_id,
        keep_existing_models=keep_existing_models,
    )
    try:
        saved = upsert_llm_provider(
            llm_provider_upsert_request=request, db_session=db_session
        )
        if chat_default is not None:
            update_default_model(
                db_session=db_session,
                provider_id=saved.id,
                model=chat_default,
                flow_type=LLMModelFlowType.CHAT,
            )
    except Exception as error:
        logger.warning("Failed to seed the local Ollama provider: %s", error)
        return False
    return True


def _add_served_extra_models(
    db_session: Session, api_base: str, extras: tuple[str, ...]
) -> None:
    """Add extra models that Ollama already serves. Leave the chat default."""
    if not extras:
        return
    listed = _listed_model_names(api_base)
    if listed is None:
        return
    present = [name for name in extras if name in listed]
    if not present:
        return
    existing = fetch_existing_llm_provider(
        name=LOCAL_OLLAMA_PROVIDER_NAME, db_session=db_session
    )
    if existing is None:
        return
    already = {model.name for model in existing.model_configurations}
    missing = [name for name in present if name not in already]
    if not missing:
        return
    if not _write_provider(
        db_session,
        api_base,
        missing,
        existing_id=existing.id,
        keep_existing_models=True,
        chat_default=None,
    ):
        return
    logger.notice(
        "Added local Ollama models %s at %s",
        ", ".join(missing),
        api_base,
    )


def seed_local_ollama_provider(db_session: Session) -> None:
    """Create the Ollama chat default when the env is set and none exists.

    Extra models named in ``ONYX_SEED_OLLAMA_EXTRA_MODELS`` are added when
    Ollama serves them. They do not replace a chat default that already exists.
    A failure here must not stop the API. The next process start tries again
    while the chat default is still missing, or while an extra model is not
    on the provider yet.
    """
    api_base = ONYX_SEED_OLLAMA_API_BASE
    model_name = ONYX_SEED_OLLAMA_MODEL
    if not api_base or not model_name:
        return
    extras = extra_model_names(ONYX_SEED_OLLAMA_EXTRA_MODELS, model_name)
    if fetch_default_model(db_session, LLMModelFlowType.CHAT) is not None:
        _add_served_extra_models(db_session, api_base, extras)
        return
    listed = _wait_for_named_model(api_base, model_name)
    if listed is None:
        return

    existing = fetch_existing_llm_provider(
        name=LOCAL_OLLAMA_PROVIDER_NAME, db_session=db_session
    )
    visible = [model_name, *[name for name in extras if name in listed]]
    if not _write_provider(
        db_session,
        api_base,
        visible,
        existing_id=existing.id if existing is not None else None,
        keep_existing_models=existing is not None,
        chat_default=model_name,
    ):
        return
    logger.notice(
        "Seeded local Ollama provider %s at %s as the chat default",
        model_name,
        api_base,
    )
