import pytest
from pydantic import ValidationError

from mandate.config import Settings, token_secrets
from mandate.errors import ConfigError

ENV_VARS = [
    "FALKORDB_HOST",
    "FALKORDB_PORT",
    "FALKORDB_PASSWORD",
    "MANDATE_API_KEY",
    "MANDATE_TOKEN_SECRETS",
    "MANDATE_MODEL",
    "ANTHROPIC_API_KEY",
    "MANDATE_LOG_LEVEL",
    "MANDATE_RATE_LIMIT_PER_MIN",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def make() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults() -> None:
    settings = make()
    assert settings.falkordb_host == "localhost"
    assert settings.falkordb_port == 6379
    assert settings.mandate_log_level == "INFO"
    assert settings.mandate_rate_limit_per_min == 600
    assert settings.mandate_api_key is None


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALKORDB_HOST", "db.internal")
    monkeypatch.setenv("FALKORDB_PORT", "6380")
    monkeypatch.setenv("MANDATE_LOG_LEVEL", "debug")
    settings = make()
    assert settings.falkordb_host == "db.internal"
    assert settings.falkordb_port == 6380
    assert settings.mandate_log_level == "DEBUG"


def test_empty_values_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FALKORDB_PASSWORD", "")
    monkeypatch.setenv("MANDATE_API_KEY", "")
    settings = make()
    assert settings.falkordb_password is None
    assert settings.mandate_api_key is None


def test_missing_api_key_rejected_on_require() -> None:
    with pytest.raises(ConfigError):
        make().require_api_key()


def test_short_api_key_rejected_on_require(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_API_KEY", "too-short")
    with pytest.raises(ConfigError):
        make().require_api_key()


def test_valid_api_key_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_API_KEY", "a" * 16)
    assert make().require_api_key() == "a" * 16


def test_secrets_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_API_KEY", "super-secret-value-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-456")
    text = repr(make())
    assert "super-secret-value-123" not in text
    assert "sk-secret-456" not in text


@pytest.mark.parametrize(("name", "value"), [("FALKORDB_PORT", "0"), ("FALKORDB_PORT", "70000")])
def test_port_range_validated(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        make()


def test_bad_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_LOG_LEVEL", "loud")
    with pytest.raises(ValidationError):
        make()


def test_rate_limit_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANDATE_RATE_LIMIT_PER_MIN", "0")
    with pytest.raises(ValidationError):
        make()


def test_default_token_secret_is_derived_never_the_admin_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MANDATE_API_KEY", "a" * 20)
    [derived] = token_secrets(make())
    assert derived != "a" * 20 and len(derived) == 64
    assert token_secrets(make()) == [derived]  # the same in every process

    monkeypatch.setenv("MANDATE_TOKEN_SECRETS", f"{'n' * 20},{'o' * 20}")
    assert token_secrets(make()) == ["n" * 20, "o" * 20]  # explicit secrets are used as given
