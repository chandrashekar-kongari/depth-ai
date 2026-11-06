from unittest.mock import MagicMock

import httpx
import pytest

from onyx.llm.constants import LlmProviderNames
from onyx.llm.seed_local_ollama import (
    LOCAL_OLLAMA_PROVIDER_NAME,
    build_ollama_seed_request,
    extra_model_names,
    ollama_model_names,
    seed_local_ollama_provider,
)


def _one_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onyx.llm.seed_local_ollama.SEED_LIST_ATTEMPTS", 1)


def test_build_request_uses_the_admin_provider_shape() -> None:
    request = build_ollama_seed_request(
        api_base="http://host.docker.internal:11434",
        model_names=["qwen3:8b"],
        existing_id=None,
    )

    assert request.name == LOCAL_OLLAMA_PROVIDER_NAME
    assert request.provider == LlmProviderNames.OLLAMA_CHAT
    assert request.api_base == "http://host.docker.internal:11434"
    assert request.api_key is None
    assert request.is_public is True
    assert len(request.model_configurations) == 1
    model = request.model_configurations[0]
    assert model.name == "qwen3:8b"
    assert model.is_visible is True
    assert model.supports_chat is True
    assert model.display_name == "Qwen 3 8B"


def test_ollama_model_names_reads_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "models": [{"name": "qwen3:8b"}, {"name": ""}, {"ignored": True}]
    }
    get = MagicMock(return_value=response)
    monkeypatch.setattr("onyx.llm.seed_local_ollama.httpx.get", get)

    names = ollama_model_names("http://127.0.0.1:11434/")

    assert names == {"qwen3:8b"}
    get.assert_called_once_with("http://127.0.0.1:11434/api/tags", timeout=5.0)


def test_extra_model_names_splits_and_drops_the_default() -> None:
    assert extra_model_names(
        " glm4:latest, glm-4.7-flash:latest, qwen3:8b, glm4:latest ",
        "qwen3:8b",
    ) == ("glm4:latest", "glm-4.7-flash:latest")
    assert extra_model_names("", "qwen3:8b") == ()


def test_seed_does_nothing_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "",
    )
    fetch_default = MagicMock()
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        fetch_default,
    )

    seed_local_ollama_provider(MagicMock())

    fetch_default.assert_not_called()


def test_seed_skips_when_a_chat_default_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_EXTRA_MODELS",
        "",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: object(),
    )
    upsert = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)

    seed_local_ollama_provider(MagicMock())

    upsert.assert_not_called()


def test_seed_writes_the_provider_and_chat_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ollama_model_names",
        lambda _api_base: {"qwen3:8b", "llama3.1:8b"},
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_existing_llm_provider",
        lambda **_kwargs: None,
    )
    saved = MagicMock()
    saved.id = 7
    upsert = MagicMock(return_value=saved)
    set_default = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)
    monkeypatch.setattr("onyx.llm.seed_local_ollama.update_default_model", set_default)

    seed_local_ollama_provider(MagicMock())

    request = upsert.call_args.kwargs["llm_provider_upsert_request"]
    assert request.model_configurations[0].name == "qwen3:8b"
    assert request.id is None
    set_default.assert_called_once()
    assert set_default.call_args.kwargs["provider_id"] == 7
    assert set_default.call_args.kwargs["model"] == "qwen3:8b"


def test_seed_skips_when_the_model_is_not_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _one_attempt(monkeypatch)
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ollama_model_names",
        lambda _api_base: {"llama3.1:8b"},
    )
    upsert = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)

    seed_local_ollama_provider(MagicMock())

    upsert.assert_not_called()


def test_seed_survives_an_unreachable_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    _one_attempt(monkeypatch)
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: None,
    )

    def raise_connect(_api_base: str) -> set[str]:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ollama_model_names",
        raise_connect,
    )
    upsert = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)

    seed_local_ollama_provider(MagicMock())

    upsert.assert_not_called()


def test_seed_retries_until_the_named_model_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("onyx.llm.seed_local_ollama.SEED_LIST_ATTEMPTS", 3)
    monkeypatch.setattr("onyx.llm.seed_local_ollama.SEED_LIST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_existing_llm_provider",
        lambda **_kwargs: None,
    )
    lists = iter([{"llama3.1:8b"}, set[str](), {"qwen3:8b"}])

    def listed(_api_base: str) -> set[str]:
        return next(lists)

    monkeypatch.setattr("onyx.llm.seed_local_ollama.ollama_model_names", listed)
    saved = MagicMock()
    saved.id = 4
    upsert = MagicMock(return_value=saved)
    set_default = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)
    monkeypatch.setattr("onyx.llm.seed_local_ollama.update_default_model", set_default)

    seed_local_ollama_provider(MagicMock())

    request = upsert.call_args.kwargs["llm_provider_upsert_request"]
    assert request.model_configurations[0].name == "qwen3:8b"
    assert set_default.call_args.kwargs["model"] == "qwen3:8b"


def test_seed_includes_extra_models_that_are_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_EXTRA_MODELS",
        "glm4:latest,glm-4.7-flash:latest,missing:latest",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ollama_model_names",
        lambda _api_base: {"qwen3:8b", "glm4:latest"},
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_existing_llm_provider",
        lambda **_kwargs: None,
    )
    saved = MagicMock()
    saved.id = 7
    upsert = MagicMock(return_value=saved)
    set_default = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)
    monkeypatch.setattr("onyx.llm.seed_local_ollama.update_default_model", set_default)

    seed_local_ollama_provider(MagicMock())

    request = upsert.call_args.kwargs["llm_provider_upsert_request"]
    assert [model.name for model in request.model_configurations] == [
        "qwen3:8b",
        "glm4:latest",
    ]
    assert request.model_configurations[1].display_name == "GLM 4"
    assert set_default.call_args.kwargs["model"] == "qwen3:8b"


def test_seed_adds_extra_models_without_changing_the_chat_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_API_BASE",
        "http://host.docker.internal:11434",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_MODEL",
        "qwen3:8b",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ONYX_SEED_OLLAMA_EXTRA_MODELS",
        "glm4:latest,glm-4.7-flash:latest",
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_default_model",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.ollama_model_names",
        lambda _api_base: {"qwen3:8b", "glm4:latest", "glm-4.7-flash:latest"},
    )
    existing = MagicMock()
    existing.id = 3
    existing.model_configurations = [MagicMock(name="qwen3:8b")]
    existing.model_configurations[0].name = "qwen3:8b"
    monkeypatch.setattr(
        "onyx.llm.seed_local_ollama.fetch_existing_llm_provider",
        lambda **_kwargs: existing,
    )
    upsert = MagicMock()
    set_default = MagicMock()
    monkeypatch.setattr("onyx.llm.seed_local_ollama.upsert_llm_provider", upsert)
    monkeypatch.setattr("onyx.llm.seed_local_ollama.update_default_model", set_default)

    seed_local_ollama_provider(MagicMock())

    request = upsert.call_args.kwargs["llm_provider_upsert_request"]
    assert [model.name for model in request.model_configurations] == [
        "glm4:latest",
        "glm-4.7-flash:latest",
    ]
    assert request.keep_existing_models is True
    assert request.id == 3
    set_default.assert_not_called()
