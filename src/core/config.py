from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ollama_base_url: str = "http://localhost:11434"
            bankheist_llm_model: str | None = Field(default=None)
    model_world_state: str = "qwen2.5:14b"
    model_strategist: str = "qwen2.5:14b"
    model_hacker: str = "mistral:7b-instruct-v0.3"
    model_robber: str = "llama3.1:8b-instruct"
    llm_temperature: float = 0.0
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "bankheist_neo4j"
    graphiti_llm_provider: str = "ollama"

    letta_base_url: str = "http://localhost:8283"
    letta_token: str = ""

    postgres_dsn: str = (
        "postgresql://bankheist:bankheist@localhost:5432/bankheist"
    )

    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    gateway_url: str = "ws://localhost:8000/ws"

    app_log_level: str = "INFO"
    app_log_format: str = "json"
    deterministic_fallback: bool = Field(default=True)
    use_graphiti: bool = Field(default=True)
    use_letta: bool = Field(default=True)
    prometheus_port: int = 9100


@lru_cache
def get_settings() -> Settings:
    return Settings()
