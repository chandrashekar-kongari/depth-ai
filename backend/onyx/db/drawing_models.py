"""Explicit local vision configuration without changing the chat default."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import add_model_to_flow, update_default_model
from onyx.db.models import LLMProvider, ModelConfiguration
from onyx.llm.constants import LlmProviderNames


def select_local_drawing_model(
    session: Session, provider_id: int, model_name: str
) -> None:
    provider = session.get(LLMProvider, provider_id)
    if provider is None or provider.provider != LlmProviderNames.OLLAMA_CHAT:
        raise ValueError("Choose an existing local Ollama provider")
    model = session.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.llm_provider_id == provider_id,
            ModelConfiguration.name == model_name,
        )
    )
    if model is None:
        model = ModelConfiguration(
            llm_provider_id=provider_id,
            name=model_name,
            display_name=model_name,
            is_visible=True,
        )
        session.add(model)
        session.flush()
    model.max_input_tokens = 8192
    model.temperature_default = 0
    model.supports_image_input = True
    session.commit()
    for flow in (LLMModelFlowType.CHAT, LLMModelFlowType.VISION):
        add_model_to_flow(session, model.id, flow)
    session.expire(model, ["llm_model_flows"])
    update_default_model(session, provider_id, model_name, LLMModelFlowType.VISION)
