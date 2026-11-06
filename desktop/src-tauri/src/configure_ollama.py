import os

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
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


def display_name(model_name: str) -> str:
    try:
        from onyx.server.manage.llm.utils import generate_ollama_display_name

        return generate_ollama_display_name(model_name)
    except Exception:
        return model_name


def config(model_name: str) -> ModelConfigurationUpsertRequest:
    fields: dict[str, object] = {
        "name": model_name,
        "is_visible": True,
        "display_name": display_name(model_name),
    }
    if "supports_chat" in ModelConfigurationUpsertRequest.model_fields:
        fields["supports_chat"] = True
    return ModelConfigurationUpsertRequest(**fields)


def extra_names(raw: str, primary: str) -> list[str]:
    names: list[str] = []
    seen = {primary}
    for part in raw.split(","):
        name = part.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def provider_request(
    api_base: str,
    model_names: list[str],
    existing_id: int | None,
    keep_existing_models: bool,
) -> LLMProviderUpsertRequest:
    return LLMProviderUpsertRequest(
        id=existing_id,
        name="Ollama",
        provider=LlmProviderNames.OLLAMA_CHAT,
        api_base=api_base,
        api_key=None,
        api_key_changed=True,
        is_public=True,
        keep_existing_models=keep_existing_models,
        model_configurations=[config(name) for name in model_names],
    )


def main() -> None:
    SqlEngine.init_engine(pool_size=2, max_overflow=0)
    api_base = os.environ.get("ONYX_SEED_OLLAMA_API_BASE", "").strip()
    primary = os.environ.get("ONYX_SEED_OLLAMA_MODEL", "").strip()
    if not api_base or not primary:
        return
    extras = extra_names(os.environ.get("ONYX_SEED_OLLAMA_EXTRA_MODELS", ""), primary)
    with get_session_with_current_tenant() as db_session:
        existing = fetch_existing_llm_provider(name="Ollama", db_session=db_session)
        if fetch_default_model(db_session, LLMModelFlowType.CHAT) is not None:
            if existing is None:
                return
            already = {model.name for model in existing.model_configurations}
            missing = [name for name in extras if name not in already]
            if not missing:
                print("ready")
                return
            upsert_llm_provider(
                provider_request(api_base, missing, existing.id, True),
                db_session,
            )
            print("added " + ",".join(missing))
            return
        saved = upsert_llm_provider(
            provider_request(
                api_base,
                [primary, *extras],
                existing.id if existing is not None else None,
                existing is not None,
            ),
            db_session,
        )
        update_default_model(
            db_session,
            saved.id,
            primary,
            LLMModelFlowType.CHAT,
        )
        print("seeded " + primary)


if __name__ == "__main__":
    main()
