"""Environment settings via pydantic-settings."""

import logging
from functools import lru_cache

from pydantic import BaseModel, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ConfidenceThreshold(BaseModel):
    auto: float
    flag: float


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # API Keys
    anthropic_api_key: str = "not-set"  # Default for dev, required for prod

    # LLM feature toggle
    llm_enabled: bool = True

    # CORS
    cors_allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
    ]

    # Authentication
    api_secret_key: str = "dev-secret-key-change-me"

    # Service URLs
    oms_api_url: str = "http://localhost:8001"
    wms_api_url: str = "http://localhost:8002"
    tms_api_url: str = "http://localhost:8003"

    # LLM
    llm_model: str = "claude-sonnet-4-20250514"

    # HTTP Client
    http_connect_timeout: float = 3.0
    http_read_timeout: float = 5.0

    # Safety
    bulk_update_cap: int = 50

    # Logging
    log_level: str = "INFO"

    # Per-intent confidence thresholds
    @property
    def confidence_thresholds(self) -> dict[str, ConfidenceThreshold]:
        return {
            "status_check": ConfidenceThreshold(auto=0.75, flag=0.45),
            "cross_system_query": ConfidenceThreshold(auto=0.80, flag=0.50),
            "analysis": ConfidenceThreshold(auto=0.80, flag=0.50),
            "action_request": ConfidenceThreshold(auto=0.90, flag=0.60),
            "report": ConfidenceThreshold(auto=0.75, flag=0.45),
        }

    def get_threshold(self, intent: str) -> ConfidenceThreshold:
        return self.confidence_thresholds[intent]

    @property
    def is_llm_available(self) -> bool:
        return self.llm_enabled and self.anthropic_api_key != "not-set"

    @model_validator(mode="after")
    def _check_api_key(self) -> "Settings":
        if self.llm_enabled and self.anthropic_api_key == "not-set":
            logger.warning(
                "ANTHROPIC_API_KEY is not set. LLM features will be unavailable."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
