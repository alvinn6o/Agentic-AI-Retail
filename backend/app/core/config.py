from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Model names
    default_model_anthropic: str = "claude-haiku-4-5-20251001"
    default_model_openai: str = "gpt-4o-mini"

    # Database
    duckdb_path: Path = Path("data/curated/warehouse.duckdb")

    # Paths
    raw_data_path: Path = Path("data/raw/data.csv")
    curated_path: Path = Path("data/curated")
    docs_path: Path = Path("data/docs")

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2"

    # App
    log_level: str = "INFO"
    max_repair_retries: int = 3

    # Enterprise dispatch
    enterprise_target_system: Literal["custom", "jira", "service_now", "sap"] = "custom"
    enterprise_api_base_url: str = ""
    enterprise_task_endpoint: str = "/tasks"
    enterprise_api_key: str = ""
    enterprise_api_timeout_seconds: float = 10.0
    enterprise_dry_run: bool = True

    # LangSmith (optional)
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "retail-ops-simulator"

    @property
    def llm_model_name(self) -> str:
        if self.llm_provider == "anthropic":
            return self.default_model_anthropic
        if self.llm_provider == "openai":
            return self.default_model_openai
        return self.ollama_model


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
