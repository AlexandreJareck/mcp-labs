"""Configuration from environment variables, with safe defaults and hard ranges."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from sqlite_consulta.query import DEFAULT_MAX_ROWS, DEFAULT_TIMEOUT_MS, Limits

TIMEOUT_ENV = "SQLITE_CONSULTA_TIMEOUT_MS"
MAX_ROWS_ENV = "SQLITE_CONSULTA_MAX_ROWS"
CONFIRM_COST_ENV = "SQLITE_CONSULTA_CONFIRM_COST"
HTTP_TOKEN_ENV = "SQLITE_CONSULTA_HTTP_TOKEN"  # noqa: S105 - the variable name, not a secret

TIMEOUT_RANGE = (50, 10_000)
MAX_ROWS_RANGE = (1, 1_000)
CONFIRM_COST_RANGE = (1, 10**12)
DEFAULT_CONFIRM_COST = 1_000_000
MIN_TOKEN_LENGTH = 16


class ConfigError(ValueError):
    """An environment variable is missing, malformed, or out of range.

    Messages name the variable and never include its value, so a secret cannot
    leak through a configuration error.
    """


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    Attributes:
        timeout_ms: Maximum execution time of a query, in milliseconds.
        max_rows: Maximum number of rows returned by a query.
        confirm_cost: Estimated cost above which the user must confirm a query.
    """

    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_rows: int = DEFAULT_MAX_ROWS
    confirm_cost: int = DEFAULT_CONFIRM_COST

    @property
    def limits(self) -> Limits:
        """The execution limits derived from the settings."""
        return Limits(timeout_ms=self.timeout_ms, max_rows=self.max_rows)


def _integer(env: Mapping[str, str], name: str, default: int, bounds: tuple[int, int]) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{name} must be an integer.") from None
    low, high = bounds
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}.")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the limits from the environment.

    Args:
        env: Environment mapping; defaults to `os.environ`.

    Returns:
        The validated settings.

    Raises:
        ConfigError: If a value is malformed or out of range.
    """
    env = os.environ if env is None else env
    return Settings(
        timeout_ms=_integer(env, TIMEOUT_ENV, DEFAULT_TIMEOUT_MS, TIMEOUT_RANGE),
        max_rows=_integer(env, MAX_ROWS_ENV, DEFAULT_MAX_ROWS, MAX_ROWS_RANGE),
        confirm_cost=_integer(env, CONFIRM_COST_ENV, DEFAULT_CONFIRM_COST, CONFIRM_COST_RANGE),
    )


def load_http_token(env: Mapping[str, str] | None = None) -> str:
    """Read the bearer token of the HTTP transport.

    Args:
        env: Environment mapping; defaults to `os.environ`.

    Returns:
        The token.

    Raises:
        ConfigError: If the token is missing or too short. The message never
            includes the value.
    """
    env = os.environ if env is None else env
    token = env.get(HTTP_TOKEN_ENV, "")
    if not token:
        raise ConfigError(f"{HTTP_TOKEN_ENV} must be set to start the HTTP transport.")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(f"{HTTP_TOKEN_ENV} must have at least {MIN_TOKEN_LENGTH} characters.")
    return token
