
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Model ────────────────────────────────────────────────────
    agent_model_provider: str = Field(default="openai", alias="AGENT_MODEL_PROVIDER")
    agent_model_name: str = Field(default="gpt-4o", alias="AGENT_MODEL_NAME")

    # OpenAI-compatible (no AGENT_ prefix)
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")

    # Anthropic (no AGENT_ prefix)
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # ── Context ──────────────────────────────────────────────────
    agent_max_tokens: int = Field(default=128000, alias="AGENT_MAX_TOKENS")
    agent_compression_threshold: float = Field(default=0.7, alias="AGENT_COMPRESSION_THRESHOLD")
    agent_enable_thinking: bool = Field(default=True, alias="AGENT_ENABLE_THINKING")

    # ── Storage ──────────────────────────────────────────────────
    agent_memory_db_path: str = Field(default="memory/agent.db", alias="AGENT_MEMORY_DB_PATH")
    agent_chroma_path: str = Field(default="memory/chroma", alias="AGENT_CHROMA_PATH")

    # ── Server ───────────────────────────────────────────────────
    agent_server_host: str = Field(default="0.0.0.0", alias="AGENT_SERVER_HOST")
    agent_server_port: int = Field(default=8000, alias="AGENT_SERVER_PORT")

    # ── Session ──────────────────────────────────────────────────
    agent_session_ttl_hours: int = Field(default=24, alias="AGENT_SESSION_TTL_HOURS")

    # ── Convenience properties ───────────────────────────────────
    @property
    def model_provider(self) -> str:
        return self.agent_model_provider

    @property
    def model_name(self) -> str:
        return self.agent_model_name

    @property
    def max_tokens(self) -> int:
        return self.agent_max_tokens

    @property
    def compression_threshold(self) -> float:
        return self.agent_compression_threshold

    @property
    def enable_thinking(self) -> bool:
        return self.agent_enable_thinking

    @property
    def memory_db_path(self) -> str:
        return self.agent_memory_db_path

    @property
    def chroma_path(self) -> str:
        return self.agent_chroma_path

    @property
    def server_host(self) -> str:
        return self.agent_server_host

    @property
    def server_port(self) -> int:
        return self.agent_server_port

    @property
    def session_ttl_hours(self) -> int:
        return self.agent_session_ttl_hours
