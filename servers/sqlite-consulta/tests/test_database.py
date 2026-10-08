import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlite_consulta.database import (
    MASK,
    SAMPLE_ROWS_LIMIT,
    UNTRUSTED_DATA_NOTICE,
    UnknownTableError,
    connect_read_only,
    describe_table,
    is_sensitive,
    list_tables,
    resolve_table,
    sample_rows,
)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO Artist (Name) VALUES ('x')",
        "UPDATE Artist SET Name = 'x'",
        "DELETE FROM Artist",
        "DROP TABLE Artist",
        "CREATE TABLE Evil (Id INTEGER)",
    ],
)
def test_connection_refuses_writes(connection: sqlite3.Connection, statement: str) -> None:
    with pytest.raises(sqlite3.OperationalError, match=r"readonly|read-only|query_only"):
        connection.execute(statement)


def test_read_only_holds_without_query_only(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA query_only = OFF")
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("DELETE FROM Artist")


def test_path_cannot_inject_uri_parameters(tmp_path: Path) -> None:
    tricky = tmp_path / "db?mode=rwc#x"
    with pytest.raises(sqlite3.OperationalError):
        connect_read_only(tricky)
    assert not tricky.exists()


def test_list_tables_returns_user_tables_with_counts(connection: sqlite3.Connection) -> None:
    assert list_tables(connection) == [
        {"name": "Album", "row_count": 1},
        {"name": "Artist", "row_count": 8},
        {"name": "Customer", "row_count": 2},
        {"name": 'Odd"Name', "row_count": 1},
    ]


@pytest.mark.parametrize("requested", ["Artist", "artist", "ARTIST"])
def test_resolve_table_is_case_insensitive(connection: sqlite3.Connection, requested: str) -> None:
    assert resolve_table(connection, requested) == "Artist"


@pytest.mark.parametrize(
    "requested",
    [
        "Missing",
        "Artist; DROP TABLE Artist",
        'Artist" --',
        "sqlite_schema",
        "sqlite_master",
        "../../etc/passwd",
        "",
    ],
)
def test_resolve_table_rejects_unknown_or_malicious_names(
    connection: sqlite3.Connection, requested: str
) -> None:
    with pytest.raises(UnknownTableError):
        resolve_table(connection, requested)


def test_describe_table_lists_columns_and_foreign_keys(connection: sqlite3.Connection) -> None:
    schema = describe_table(connection, "album")
    assert schema["table"] == "Album"
    assert schema["columns"][0] == {
        "name": "AlbumId",
        "type": "INTEGER",
        "not_null": False,
        "primary_key": True,
        "sensitive": False,
    }
    assert schema["columns"][1]["not_null"] is True
    assert schema["foreign_keys"] == [
        {"column": "ArtistId", "references_table": "Artist", "references_column": "ArtistId"}
    ]


def test_describe_table_flags_sensitive_columns(connection: sqlite3.Connection) -> None:
    schema = describe_table(connection, "Customer")
    sensitive = {column["name"] for column in schema["columns"] if column["sensitive"]}
    assert sensitive == {"Phone", "Email"}


def test_describe_table_handles_quotes_in_names(connection: sqlite3.Connection) -> None:
    schema = describe_table(connection, 'odd"name')
    assert [column["name"] for column in schema["columns"]] == ["Id", "Payload"]


def test_describe_unknown_table_raises(connection: sqlite3.Connection) -> None:
    with pytest.raises(UnknownTableError):
        describe_table(connection, "Nope")


def test_sample_rows_respects_fixed_limit(connection: sqlite3.Connection) -> None:
    result = sample_rows(connection, "Artist")
    assert result["limit"] == SAMPLE_ROWS_LIMIT
    assert len(result["rows"]) == SAMPLE_ROWS_LIMIT
    assert result["columns"] == ["ArtistId", "Name"]
    assert result["masked_columns"] == []


def test_sample_rows_masks_sensitive_columns(connection: sqlite3.Connection) -> None:
    result = sample_rows(connection, "customer")
    assert result["masked_columns"] == ["Phone", "Email"]
    assert result["rows"] == [
        [1, "Ana", "Brazil", MASK, MASK],
        [2, "Bruno", "Portugal", None, MASK],
    ]
    flat = repr(result)
    assert "example.com" not in flat
    assert "+55" not in flat


def test_sample_rows_renders_blobs_without_raw_bytes(connection: sqlite3.Connection) -> None:
    result = sample_rows(connection, 'Odd"Name')
    assert result["rows"] == [[1, "<blob: 2 bytes>"]]


def test_sample_rows_marks_data_as_untrusted(injection_db_path: Path, injection_text: str) -> None:
    before = injection_db_path.read_bytes()
    with closing(connect_read_only(injection_db_path)) as conn:
        result = sample_rows(conn, "Artist")
    assert result["rows"] == [[8, injection_text]]
    assert result["notice"] == UNTRUSTED_DATA_NOTICE
    assert injection_db_path.read_bytes() == before


def test_sample_rows_unknown_table_raises(connection: sqlite3.Connection) -> None:
    with pytest.raises(UnknownTableError):
        sample_rows(connection, "Nope")


@pytest.mark.parametrize(
    ("table", "column", "expected"),
    [
        ("Customer", "Email", True),
        ("customer", "EMAIL", True),
        ("Employee", "BirthDate", True),
        ("Invoice", "BillingAddress", True),
        ("Invoice", "BillingCountry", False),
        ("Customer", "Country", False),
        ("Artist", "Email", False),
    ],
)
def test_is_sensitive(table: str, column: str, expected: bool) -> None:
    assert is_sensitive(table, column) is expected
