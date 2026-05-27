from langchain_core.language_models import BaseChatModel

from src.agent.config import AgentConfig


def resolve_model(config: AgentConfig) -> BaseChatModel:
    if config.model_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=config.model_name,
            anthropic_api_key=config.anthropic_api_key,
        )
    else:
        from langchain_openai import ChatOpenAI

        kwargs = {}
        if config.enable_thinking:
            kwargs["enable_thinking"] = True

        return ChatOpenAI(
            model=config.model_name,
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model_kwargs=kwargs,
        )
