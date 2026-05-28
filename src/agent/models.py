from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from src.agent.config import AgentConfig


def resolve_model(config: AgentConfig) -> BaseChatModel:
    """使用 init_chat_model 统一初始化，根据 provider 前缀自动选择正确的模型类。

    例如：
    - "deepseek:deepseek-chat" → ChatDeepSeek（支持 reasoning_content）
    - "openai:gpt-4o" → ChatOpenAI
    - "anthropic:claude-sonnet-4-5" → ChatAnthropic
    """
    model_id = f"{config.model_provider}:{config.model_name}"

    # Anthropic 使用独立的 API key
    if config.model_provider == "anthropic":
        return init_chat_model(
            model_id,
            anthropic_api_key=config.anthropic_api_key,
        )

    # OpenAI 兼容接口（含 DeepSeek、OpenRouter 等）
    return init_chat_model(
        model_id,
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
    )
