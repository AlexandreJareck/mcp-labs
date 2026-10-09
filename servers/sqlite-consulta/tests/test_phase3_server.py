"""Phase 3 behavior of the MCP server: resources, confirmation, audit, and HTTP."""

import json
import logging
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer
from mcp.types import ElicitRequestParams, ElicitResult
from sqlite_consulta import audit, chinook, config, server
from sqlite_consulta.dictionary import DICTIONARY_URI, SCHEMA_URI
from starlette.testclient import TestClient

CHEAP_SQL = "SELECT Name FROM Artist WHERE ArtistId = 1"
COSTLY_SQL = "SELECT count(*) AS n FROM Artist a, Artist b, Artist c"
LOW_THRESHOLD = config.Settings(confirm_cost=100)
AUDIT = "sqlite_consulta.audit"


def _audit_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == AUDIT]


@pytest.fixture(autouse=True)
def _reset_confirmation_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "_last_request", None)


@pytest.fixture
async def client(db_path: Path) -> AsyncIterator[Client]:
    async with Client(server.create_server(db_path), raise_exceptions=True) as connected:
        yield connected


# --- Resources ----------------------------------------------------------------


@pytest.mark.anyio
async def test_resources_are_listed(client: Client) -> None:
    listed = (await client.list_resources()).resources
    assert {str(resource.uri) for resource in listed} == {SCHEMA_URI, DICTIONARY_URI}
    assert all(resource.mime_type == "application/json" for resource in listed)


@pytest.mark.anyio
async def test_schema_resource(client: Client) -> None:
    contents = (await client.read_resource(SCHEMA_URI)).contents
    document = json.loads(contents[0].text)  # type: ignore[union-attr]
    assert document["dialect"] == "SQLite"
    assert "Customer" in [table["table"] for table in document["tables"]]


@pytest.mark.anyio
async def test_dictionary_resource(client: Client, sensitive_values: tuple[str, ...]) -> None:
    contents = (await client.read_resource(DICTIONARY_URI)).contents
    text = contents[0].text  # type: ignore[union-attr]
    document = json.loads(text)
    customer = next(t for t in document["tables"] if t["name"] == "Customer")
    assert customer["description"]
    assert all(value not in text for value in sensitive_values)


# --- Confirmation (elicitation) -------------------------------------------------


def _callback(action: str, confirm: bool, asked: list[str]) -> Any:
    async def callback(context: Any, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params.message)
        if action == "accept":
            return ElicitResult(action="accept", content={"confirm": confirm})
        return ElicitResult(action=action)  # type: ignore[arg-type]

    return callback


@pytest.mark.anyio
async def test_cheap_queries_never_ask(db_path: Path) -> None:
    asked: list[str] = []
    mcp = server.create_server(db_path, LOW_THRESHOLD)
    async with Client(mcp, elicitation_callback=_callback("accept", True, asked)) as client:
        result = await client.call_tool("run_query", {"sql": CHEAP_SQL})
    assert not result.is_error
    assert asked == []


@pytest.mark.anyio
async def test_confirmed_expensive_query_runs(
    db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    asked: list[str] = []
    mcp = server.create_server(db_path, LOW_THRESHOLD)
    async with Client(mcp, elicitation_callback=_callback("accept", True, asked)) as client:
        result = await client.call_tool("run_query", {"sql": COSTLY_SQL})
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["rows"] == [[512]]
    assert len(asked) == 1
    assert "Run it anyway?" in asked[0]
    events = [(line["event"], line.get("decision")) for line in _audit_lines(caplog)]
    assert events == [("confirmation_requested", None), ("query", "confirmed")]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "confirm"), [("accept", False), ("decline", True), ("cancel", True)]
)
async def test_unconfirmed_expensive_query_does_not_run(
    db_path: Path, caplog: pytest.LogCaptureFixture, action: str, confirm: bool
) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    asked: list[str] = []
    mcp = server.create_server(db_path, LOW_THRESHOLD)
    async with Client(mcp, elicitation_callback=_callback(action, confirm, asked)) as client:
        result = await client.call_tool("run_query", {"sql": COSTLY_SQL})
    assert result.is_error
    assert "was not confirmed" in str(result.content)
    final = _audit_lines(caplog)[-1]
    assert (final["decision"], final["row_count"]) == ("declined", None)


@pytest.mark.anyio
async def test_client_without_elicitation_gets_a_clear_refusal(
    db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    async with Client(server.create_server(db_path, LOW_THRESHOLD)) as client:
        result = await client.call_tool("run_query", {"sql": COSTLY_SQL})
    assert result.is_error
    assert "cannot ask the user to confirm" in str(result.content)
    (line,) = _audit_lines(caplog)
    assert (line["decision"], line["reason"]) == ("declined", "client cannot confirm")


@pytest.mark.anyio
async def test_invalid_sql_is_reported_without_asking(
    db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    asked: list[str] = []
    mcp = server.create_server(db_path, LOW_THRESHOLD)
    async with Client(mcp, elicitation_callback=_callback("accept", True, asked)) as client:
        result = await client.call_tool("run_query", {"sql": "DELETE FROM Artist"})
    assert result.is_error
    assert "Query rejected (ast)" in str(result.content)
    assert asked == []
    (line,) = _audit_lines(caplog)
    assert (line["decision"], line["reason"]) == ("rejected", "ast")


# --- Audit and limits through the tool ------------------------------------------


@pytest.mark.anyio
async def test_audit_line_for_allowed_query(
    client: Client, caplog: pytest.LogCaptureFixture, sensitive_values: tuple[str, ...]
) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    sql = "SELECT FirstName, Email FROM Customer WHERE Country = 'Brazil'"
    result = await client.call_tool("run_query", {"sql": sql})
    assert not result.is_error
    (line,) = _audit_lines(caplog)
    assert line["decision"] == "allowed"
    assert line["row_count"] == 1
    assert "Brazil" not in line["sql_normalized"]
    assert all(value not in json.dumps(line) for value in sensitive_values)


@pytest.mark.anyio
async def test_limits_from_settings_apply(db_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    settings = config.Settings(max_rows=3, timeout_ms=100)
    confirm = _callback("accept", True, [])
    async with Client(
        server.create_server(db_path, settings), elicitation_callback=confirm
    ) as client:
        rows = await client.call_tool("run_query", {"sql": "SELECT Name FROM Artist"})
        slow = await client.call_tool(
            "run_query",
            {
                "sql": "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
                "SELECT count(*) FROM r"
            },
        )
    assert rows.structured_content is not None
    assert rows.structured_content["row_count"] == 3
    assert rows.structured_content["truncated"] is True
    assert slow.is_error
    assert "time limit" in str(slow.content)
    decisions = [line.get("decision") for line in _audit_lines(caplog)]
    assert decisions == ["allowed", None, "rejected"]  # None: confirmation_requested
    assert _audit_lines(caplog)[-1]["reason"] == "limits"


@pytest.mark.anyio
async def test_runtime_failures_are_audited(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT)
    result = await client.call_tool("run_query", {"sql": "SELECT ntile(0) OVER () AS x"})
    assert result.is_error
    (line,) = _audit_lines(caplog)
    assert (line["decision"], line["reason"]) == ("failed", "execution failed")


# --- HTTP transport ---------------------------------------------------------------

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def http_token() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def http_client(db_path: Path, http_token: str) -> Iterator[TestClient]:
    auth = server.HttpAuth(token=http_token, port=8765)
    app = server.create_server(db_path, http_auth=auth).streamable_http_app()
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def test_http_without_token_is_refused(http_client: TestClient) -> None:
    response = http_client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_http_with_wrong_token_is_refused(http_client: TestClient, http_token: str) -> None:
    wrong = secrets.token_urlsafe(32)
    assert wrong != http_token
    response = http_client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": f"Bearer {wrong}"}
    )
    assert response.status_code == 401


def test_http_with_token_is_accepted(http_client: TestClient, http_token: str) -> None:
    response = http_client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": f"Bearer {http_token}"}
    )
    assert response.status_code == 200
    assert http_token not in response.text


def test_http_rejects_foreign_host_even_with_token(
    http_client: TestClient, http_token: str
) -> None:
    response = http_client.post(
        "/mcp",
        json=INITIALIZE,
        headers={
            **MCP_HEADERS,
            "Authorization": f"Bearer {http_token}",
            "Host": "attacker.example",
        },
    )
    assert response.status_code == 421


def test_http_auth_repr_hides_the_token(http_token: str) -> None:
    auth = server.HttpAuth(token=http_token, port=8000)
    assert http_token not in repr(auth)
    assert http_token not in str(auth)


@pytest.mark.anyio
async def test_static_token_verifier(http_token: str) -> None:
    verifier = server.StaticTokenVerifier(http_token)
    accepted = await verifier.verify_token(http_token)
    assert accepted is not None
    assert http_token not in repr(accepted)
    assert await verifier.verify_token(http_token + "x") is None
    assert await verifier.verify_token("") is None


# --- Command line -------------------------------------------------------------------


@pytest.fixture
def no_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
    """Skip database verification and capture how the server would be started."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setattr(chinook, "verify_database", lambda path: None)
    monkeypatch.setattr(
        MCPServer,
        "run",
        lambda self, transport="stdio", **kwargs: calls.append({"transport": transport, **kwargs}),
    )
    monkeypatch.setattr(audit, "configure_audit_logging", lambda: None)
    for name in (config.TIMEOUT_ENV, config.MAX_ROWS_ENV, config.CONFIRM_COST_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(config.HTTP_TOKEN_ENV, raising=False)
    return calls


def test_main_defaults_to_stdio(no_run: list[dict[str, Any]]) -> None:
    server.main([])
    assert no_run == [{"transport": "stdio"}]


def test_main_http_requires_token(
    no_run: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        server.main(["serve", "--transport", "http"])
    assert exit_info.value.code == 1
    assert config.HTTP_TOKEN_ENV in caplog.text
    assert no_run == []


def test_main_http_listens_on_localhost_only(
    no_run: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    http_token: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    monkeypatch.setenv(config.HTTP_TOKEN_ENV, http_token)
    server.main(["serve", "--transport", "http", "--port", "8123"])
    assert no_run == [{"transport": "streamable-http", "host": "127.0.0.1", "port": 8123}]
    assert http_token not in caplog.text


@pytest.mark.parametrize("port", ["80", "70000"])
def test_main_rejects_privileged_or_invalid_ports(
    no_run: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, http_token: str, port: str
) -> None:
    monkeypatch.setenv(config.HTTP_TOKEN_ENV, http_token)
    with pytest.raises(SystemExit):
        server.main(["serve", "--transport", "http", "--port", port])
    assert no_run == []


def test_main_rejects_invalid_limits(
    no_run: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(config.MAX_ROWS_ENV, "0")
    with pytest.raises(SystemExit):
        server.main(["serve"])
    assert no_run == []
