"""Runtime configuration.

Values come from environment variables or a local ``.env`` file (never committed).
Settings are created once at the edge (API startup, CLI) and passed down; domain code
never reads configuration itself.
"""

from __future__ import annotations

import hashlib
import hmac
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mandate.errors import ConfigError

MIN_API_KEY_LENGTH = 16
# Label for deriving the default agent-token secret from the admin key (domain separation).
TOKEN_SECRET_LABEL = b"mandate/agent-token/v1"
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    falkordb_host: str = "localhost"
    falkordb_port: int = Field(default=6379, ge=1, le=65535)
    falkordb_password: SecretStr | None = None
    falkordb_max_in_flight: int = Field(default=16, ge=1, le=256)

    mandate_api_key: SecretStr | None = None
    # Extra scoped keys: id:secret:role:tenants, separated by ';' (see mandate.api.keys).
    mandate_api_keys: SecretStr | None = None
    # Agent-token signing secrets, newest first; older ones still verify (rotation).
    mandate_token_secrets: SecretStr | None = None
    mandate_token_ttl_seconds: int = Field(default=86_400, ge=60)
    # Console sign-in sessions: how long one lasts, and whether the cookie needs HTTPS.
    # Browsers treat http://localhost and 127.0.0.1 as secure, so local use works either way.
    mandate_session_ttl_seconds: int = Field(default=43_200, ge=300, le=2_592_000)
    mandate_session_idle_seconds: int = Field(default=7_200, ge=300, le=2_592_000)
    mandate_cookie_secure: bool = True
    # Webhooks: the console's public address (for the approval links in messages), how often
    # the notifier looks for held actions (0 turns it off), how long a messaged link lasts,
    # and whether webhooks may point at private addresses (local testing only).
    mandate_public_url: str | None = None
    mandate_notify_interval_seconds: float = Field(default=3.0, ge=0)
    mandate_notify_link_ttl_seconds: int = Field(default=3600, ge=60, le=86_400)
    mandate_webhook_allow_private: bool = False
    # Live agents only (the authority engine never calls a model). The provider is anthropic,
    # groq, openai, or openai-compatible (any server speaking that API: set the base URL).
    mandate_llm_provider: str = "anthropic"
    mandate_model: str = "claude-sonnet-5-5"  # the model when the provider is anthropic
    mandate_llm_model: str | None = None  # the model for any other provider
    mandate_llm_base_url: str | None = None
    mandate_llm_api_key: SecretStr | None = None  # for openai-compatible servers
    anthropic_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # Serve the built console (ui/dist) from the API, for a one-container deployment.
    mandate_static_dir: Path | None = None

    mandate_log_level: str = "INFO"
    mandate_rate_limit_per_min: int = Field(default=600, ge=1)
    # Where GET /v1/eval/latest looks for evaluation results (a folder per run).
    mandate_results_dir: Path = Path("docs/results")

    @field_validator("mandate_log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"log level must be one of {sorted(LOG_LEVELS)}")
        return level

    def require_api_key(self) -> str:
        """Return the admin API key, or raise if it is missing or too short."""
        if self.mandate_api_key is None:
            raise ConfigError("MANDATE_API_KEY is not set")
        key = self.mandate_api_key.get_secret_value()
        if len(key) < MIN_API_KEY_LENGTH:
            raise ConfigError(f"MANDATE_API_KEY must be at least {MIN_API_KEY_LENGTH} characters")
        return key


def token_secrets(settings: Settings) -> list[str]:
    """Agent-token signing secrets, newest first.

    Unset, the one secret is derived from the admin key rather than being the admin key, so
    the admin key itself never signs anything an agent holds.
    """
    if settings.mandate_token_secrets is None:
        admin_key = settings.require_api_key().encode()
        return [hmac.new(admin_key, TOKEN_SECRET_LABEL, hashlib.sha256).hexdigest()]
    secrets = [s.strip() for s in settings.mandate_token_secrets.get_secret_value().split(",")]
    secrets = [s for s in secrets if s]
    if not secrets or any(len(s) < MIN_API_KEY_LENGTH for s in secrets):
        raise ConfigError(
            f"MANDATE_TOKEN_SECRETS needs at least one secret of {MIN_API_KEY_LENGTH}+ characters"
        )
    return secrets


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process. Call at the edge, then pass the object down."""
    return Settings()
