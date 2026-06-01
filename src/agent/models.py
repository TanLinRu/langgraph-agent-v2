"""Model resolution — supports per-agent model overrides."""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from src.agent.config import AgentConfig


def resolve_model(config: AgentConfig, model_override: str = None, temperature: float = None, max_tokens: int = None) -> BaseChatModel:
    """Resolve a chat model, with optional per-agent overrides.

    Args:
        config: Global agent config (from .env)
        model_override: Per-agent model string (e.g. "deepseek:deepseek-chat", "openai:gpt-4o")
        temperature: Per-agent temperature override
        max_tokens: Per-agent max_tokens override (used as max_output_tokens)
    """
    if model_override:
        model_id = model_override
    else:
        model_id = f"{config.model_provider}:{config.model_name}"

    kwargs = {}

    # Temperature override
    if temperature is not None:
        kwargs["temperature"] = temperature

    # Max tokens override
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    # Anthropic uses separate API key
    if model_id.startswith("anthropic:"):
        return init_chat_model(
            model_id,
            anthropic_api_key=config.anthropic_api_key,
            **kwargs,
        )

    # OpenAI-compatible (DeepSeek, OpenRouter, etc.)
    return init_chat_model(
        model_id,
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
        **kwargs,
    )
