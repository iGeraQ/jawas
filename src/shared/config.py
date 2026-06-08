import json
from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources.providers.dotenv import DotEnvSettingsSource
from pydantic_settings.sources.providers.env import EnvSettingsSource

from src.enricher.providers.base import AIProviderName


def _comma_decode(value: Any) -> Any:
    """Fallback: split a comma-separated string into a list."""
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return value


class _CommaEnvSource(EnvSettingsSource):
    """Reads from os.environ, accepting CSV strings for list[str] fields."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except (json.JSONDecodeError, ValueError):
            return _comma_decode(value)


class _CommaDotEnvSource(DotEnvSettingsSource):
    """Reads from .env file, accepting CSV strings for list[str] fields."""

    def decode_complex_value(self, field_name: str, field: FieldInfo, value: Any) -> Any:
        try:
            return super().decode_complex_value(field_name, field, value)
        except (json.JSONDecodeError, ValueError):
            return _comma_decode(value)


class Settings(BaseSettings):
    database_url: str
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_admin_chat_id: int
    raw_items_queue_url: str
    approved_drafts_queue_url: str
    dlq_url: str
    jina_api_key: str

    aws_region: str = "us-east-1"
    aws_access_key_id: str = "test"
    aws_secret_access_key: str = "test"
    sqs_endpoint_url: str | None = None
    relevance_threshold: int = 7
    fetch_interval_hours: int = 2

    ai_provider: AIProviderName = AIProviderName.ANTHROPIC
    gemini_api_key: str = ""

    x_consumer_key: str = ""
    x_consumer_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "jawas/1.0"

    x_profiles: list[str] = Field(default_factory=list)
    hn_keywords: list[str] = Field(
        default_factory=lambda: ["AI", "LLM", "Claude", "GPT", "machine learning", "anthropic", "openai"]
    )
    reddit_subreddits: list[str] = Field(
        default_factory=lambda: ["MachineLearning", "artificial", "LocalLLaMA"]
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (
            kwargs["init_settings"],
            _CommaEnvSource(settings_cls),
            _CommaDotEnvSource(settings_cls, env_file=".env", env_file_encoding="utf-8"),
        )


settings = Settings()
