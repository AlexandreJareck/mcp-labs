import secrets

import pytest
from sqlite_consulta import config
from sqlite_consulta.config import ConfigError, Settings, load_http_token, load_settings
from sqlite_consulta.query import DEFAULT_MAX_ROWS, DEFAULT_TIMEOUT_MS


def test_defaults_are_safe() -> None:
    settings = load_settings({})
    assert settings == Settings()
    assert settings.timeout_ms == DEFAULT_TIMEOUT_MS == 2000
    assert settings.max_rows == DEFAULT_MAX_ROWS == 200
    assert settings.confirm_cost == config.DEFAULT_CONFIRM_COST == 1_000_000
    assert settings.limits.timeout_ms == 2000
    assert settings.limits.max_rows == 200


def test_values_are_read_from_the_environment() -> None:
    settings = load_settings(
        {
            config.TIMEOUT_ENV: "500",
            config.MAX_ROWS_ENV: " 50 ",
            config.CONFIRM_COST_ENV: "123",
        }
    )
    assert (settings.timeout_ms, settings.max_rows, settings.confirm_cost) == (500, 50, 123)


def test_blank_values_use_the_default() -> None:
    assert load_settings({config.MAX_ROWS_ENV: "  "}).max_rows == DEFAULT_MAX_ROWS


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (config.TIMEOUT_ENV, "49"),
        (config.TIMEOUT_ENV, "10001"),
        (config.TIMEOUT_ENV, "-1"),
        (config.MAX_ROWS_ENV, "0"),
        (config.MAX_ROWS_ENV, "1001"),
        (config.CONFIRM_COST_ENV, "0"),
        (config.CONFIRM_COST_ENV, str(10**12 + 1)),
        (config.TIMEOUT_ENV, "fast"),
        (config.MAX_ROWS_ENV, "1.5"),
    ],
)
def test_invalid_values_fail_instead_of_falling_back(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        load_settings({name: value})


def test_error_messages_do_not_echo_values() -> None:
    marker = secrets.token_hex(8)
    with pytest.raises(ConfigError) as error:
        load_settings({config.TIMEOUT_ENV: marker})
    assert marker not in str(error.value)


def test_http_token_is_read_from_the_environment() -> None:
    token = secrets.token_urlsafe(24)
    assert load_http_token({config.HTTP_TOKEN_ENV: token}) == token


def test_http_token_is_required() -> None:
    with pytest.raises(ConfigError, match=config.HTTP_TOKEN_ENV):
        load_http_token({})


def test_short_http_token_is_rejected_without_echoing_it() -> None:
    short = secrets.token_hex(3)
    with pytest.raises(ConfigError) as error:
        load_http_token({config.HTTP_TOKEN_ENV: short})
    assert short not in str(error.value)
    assert str(config.MIN_TOKEN_LENGTH) in str(error.value)


def test_settings_default_to_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    token = secrets.token_urlsafe(24)
    monkeypatch.setenv(config.MAX_ROWS_ENV, "7")
    monkeypatch.setenv(config.HTTP_TOKEN_ENV, token)
    assert load_settings().max_rows == 7
    assert load_http_token() == token
