"""Build chat clients from settings. Returns None when a model path is not configured.

There is intentionally NO fallback between clients: if Model 3 is not configured,
build_model3_client() returns None and the graph reports 503, it never substitutes Model 1/2.
"""

from __future__ import annotations

from app.core.config import Settings
from app.llm.base import ChatClient
from app.llm.openai_compat import OpenAICompatibleChatClient


def build_primary_client(settings: Settings) -> ChatClient | None:
    """The single hosted model shared by Model 1 and Model 2."""
    if not settings.primary_configured:
        return None
    if settings.llm_provider == "openai":
        return OpenAICompatibleChatClient(
            provider="openai",
            model=settings.openai_chat_model,
            api_key=settings.primary_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            max_output_tokens=settings.llm_max_output_tokens,
            token_param="max_completion_tokens",
            temperature=settings.llm_temperature,
            reasoning_effort=settings.llm_reasoning_effort,
        )
    return OpenAICompatibleChatClient(
        provider="openrouter",
        model=settings.openrouter_chat_model,
        api_key=settings.primary_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        max_output_tokens=settings.llm_max_output_tokens,
        token_param="max_tokens",
        temperature=settings.llm_temperature,
        reasoning_effort=settings.llm_reasoning_effort,
        extra_headers={"X-Title": "CU Student Helpdesk (academic prototype)"},
    )


def build_model3_client(settings: Settings, *, served_model: str | None = None) -> ChatClient | None:
    """Model 3: OpenAI-compatible endpoint (e.g. vLLM) serving the LoRA adapter under MODEL3_MODEL.

    `served_model` lets the evaluation script call the *base* model on the same endpoint
    (MODEL3_ABLATION_MODEL) for the PEFT ablation. The chat API never passes it.
    """
    if not settings.model3_configured:
        return None
    return OpenAICompatibleChatClient(
        provider="model3-endpoint",
        model=served_model or settings.model3_model,
        api_key=settings.model3_api_key.get_secret_value() if settings.model3_api_key else "",
        base_url=settings.model3_base_url,
        timeout=settings.model3_timeout_seconds,
        max_retries=settings.model3_max_retries,
        max_output_tokens=settings.llm_max_output_tokens,
        token_param="max_tokens",
        temperature=settings.model3_temperature,
    )
