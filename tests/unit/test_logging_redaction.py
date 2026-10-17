import io
import json

import pytest

from mandate.logging import REDACTED, configure_logging, get_logger


def emit(level: str, **fields: object) -> list[dict[str, object]]:
    stream = io.StringIO()
    configure_logging(level, stream=stream)
    get_logger("test").info("hello", **fields)
    get_logger("test").debug("detail")
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_secret_keys_redacted() -> None:
    (record,) = emit(
        "INFO",
        api_key="abc",
        auth_token="def",
        client_secret="ghi",
        db_password="jkl",
        user="dana",
    )
    for name in ("api_key", "auth_token", "client_secret", "db_password"):
        assert record[name] == REDACTED
    assert record["user"] == "dana"


def test_output_is_json_with_level_and_timestamp() -> None:
    (record,) = emit("INFO")
    assert record["event"] == "hello"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_level_filtering() -> None:
    records = emit("DEBUG")
    assert [r["event"] for r in records] == ["hello", "detail"]


def test_unknown_level_rejected() -> None:
    with pytest.raises(ValueError):
        configure_logging("LOUD")
