import urllib.error
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from mcp import Client
from mcp.server import MCPServer
from sqlite_consulta import chinook, server
from sqlite_consulta.database import MASK

TOOL_NAMES = {"list_tables", "describe_table", "sample_rows", "run_query", "search_context"}


@pytest.fixture
async def client(db_path: Path) -> AsyncIterator[Client]:
    async with Client(server.create_server(db_path), raise_exceptions=True) as connected:
        yield connected


@pytest.mark.anyio
async def test_exposes_only_read_only_tools(client: Client) -> None:
    tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == TOOL_NAMES
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.output_schema is not None


@pytest.mark.anyio
async def test_list_tables_tool(client: Client) -> None:
    result = await client.call_tool("list_tables", {})
    assert not result.is_error
    assert result.structured_content is not None
    names = [table["name"] for table in result.structured_content["tables"]]
    assert names == ["Album", "Artist", "Customer", "Employee", "Invoice", 'Odd"Name']


@pytest.mark.anyio
async def test_describe_table_tool(client: Client) -> None:
    result = await client.call_tool("describe_table", {"table": "Album"})
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["foreign_keys"][0]["references_table"] == "Artist"


@pytest.mark.anyio
async def test_sample_rows_tool_masks_sensitive_columns(client: Client) -> None:
    result = await client.call_tool("sample_rows", {"table": "Customer"})
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["rows"][0][-1] == MASK
    assert "example.com" not in str(result.content)


@pytest.mark.anyio
@pytest.mark.parametrize("tool", ["describe_table", "sample_rows"])
async def test_unknown_table_is_a_tool_error(client: Client, tool: str) -> None:
    result = await client.call_tool(tool, {"table": "Artist; DROP TABLE Artist"})
    assert result.is_error
    assert "Unknown table" in str(result.content)


@pytest.mark.anyio
async def test_table_name_length_is_limited(client: Client) -> None:
    result = await client.call_tool("sample_rows", {"table": "x" * 129})
    assert result.is_error


@pytest.mark.anyio
async def test_run_query_tool_masks_sensitive_columns(client: Client) -> None:
    result = await client.call_tool(
        "run_query", {"sql": "SELECT FirstName, Email AS contact FROM Customer ORDER BY 1"}
    )
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["rows"] == [["Ana", MASK], ["Bruno", MASK]]
    assert result.structured_content["masked_columns"] == ["contact"]
    assert "example.com" not in str(result.content)


@pytest.mark.anyio
async def test_run_query_tool_reports_the_blocking_layer(client: Client) -> None:
    result = await client.call_tool("run_query", {"sql": "DROP TABLE Customer"})
    assert result.is_error
    assert "Query rejected (ast)" in str(result.content)


@pytest.mark.anyio
async def test_run_query_tool_reports_runtime_errors(client: Client) -> None:
    result = await client.call_tool("run_query", {"sql": "SELECT ntile(0) OVER () AS x"})
    assert result.is_error
    assert "query failed" in str(result.content)


@pytest.mark.anyio
async def test_tools_never_write(client: Client, db_path: Path) -> None:
    before = db_path.read_bytes()
    for tool, args in [
        ("list_tables", {}),
        ("describe_table", {"table": "Artist"}),
        ("sample_rows", {"table": "Artist"}),
        ("run_query", {"sql": "SELECT * FROM Customer"}),
        ("run_query", {"sql": "DELETE FROM Customer"}),
    ]:
        await client.call_tool(tool, args)
    assert db_path.read_bytes() == before


def test_main_refuses_to_start_without_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    with pytest.raises(SystemExit) as exit_info:
        server.main([])
    assert exit_info.value.code == 1
    assert "download-db" in caplog.text


def test_main_runs_server_after_verifying_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    verified: list[Path] = []
    ran: list[bool] = []
    monkeypatch.setattr(chinook, "verify_database", verified.append)
    monkeypatch.setattr(MCPServer, "run", lambda self: ran.append(True))
    server.main(["serve"])
    assert verified == [tmp_path.resolve() / chinook.CHINOOK.filename]
    assert ran == [True]


def test_main_download_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    downloaded: list[Path] = []
    monkeypatch.setattr(chinook, "download_database", downloaded.append)
    server.main(["download-db"])
    assert downloaded == [tmp_path.resolve() / chinook.CHINOOK.filename]


def test_main_download_network_error_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))

    def fail(path: Path) -> Path:
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(chinook, "download_database", fail)
    with pytest.raises(SystemExit) as exit_info:
        server.main(["download-db"])
    assert exit_info.value.code == 1
    assert "Could not obtain the database" in caplog.text
