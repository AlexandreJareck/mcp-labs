import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlite_consulta import database, dictionary

# Column count of every table of the pinned Chinook release (v1.4.5).
CHINOOK_COLUMNS: dict[str, int] = {
    "Album": 3,
    "Artist": 2,
    "Customer": 13,
    "Employee": 15,
    "Genre": 2,
    "Invoice": 9,
    "InvoiceLine": 5,
    "MediaType": 2,
    "Playlist": 2,
    "PlaylistTrack": 2,
    "Track": 9,
}


def test_packaged_dictionary_describes_every_chinook_column() -> None:
    source = dictionary.load_source()
    assert {name: len(t["columns"]) for name, t in source["tables"].items()} == CHINOOK_COLUMNS
    assert all(t["description"] for t in source["tables"].values())
    assert all(text for t in source["tables"].values() for text in t["columns"].values())


def test_every_sensitive_column_is_documented_as_masked() -> None:
    source = dictionary.load_source()
    for table, columns in database.SENSITIVE_COLUMNS.items():
        described = next(t for name, t in source["tables"].items() if name.lower() == table)
        for column in columns:
            text = next(v for k, v in described["columns"].items() if k.lower() == column)
            assert "masked" in text.lower()


def test_dictionary_matches_the_real_database_when_available() -> None:
    path = Path.home() / ".cache" / "mcp-labs" / "sqlite-consulta" / "chinook-v1.4.5.sqlite"
    if not path.is_file():
        pytest.skip("Chinook database not downloaded")
    with closing(database.connect_read_only(path)) as conn:
        document = dictionary.build_dictionary(conn)
    assert {t["name"]: len(t["columns"]) for t in document["tables"]} == CHINOOK_COLUMNS
    assert all(c["description"] for t in document["tables"] for c in t["columns"])


def test_schema_document(connection: sqlite3.Connection) -> None:
    document = dictionary.build_schema(connection)
    assert document["dialect"] == "SQLite"
    names = [table["table"] for table in document["tables"]]
    assert names == ["Album", "Artist", "Customer", "Employee", "Invoice", 'Odd"Name']
    customer = next(t for t in document["tables"] if t["table"] == "Customer")
    assert {c["name"] for c in customer["columns"] if c["sensitive"]} == {"Phone", "Email"}


def test_dictionary_joins_descriptions_with_the_live_schema(
    connection: sqlite3.Connection,
) -> None:
    document = dictionary.build_dictionary(connection)
    customer = next(t for t in document["tables"] if t["name"] == "Customer")
    assert customer["row_count"] == 2
    assert customer["description"]
    email = next(c for c in customer["columns"] if c["name"] == "Email")
    assert email["sensitive"] is True
    assert email["description"]
    assert document["sensitive_columns_note"] == dictionary.SENSITIVE_NOTE


def test_unknown_tables_are_listed_without_description(connection: sqlite3.Connection) -> None:
    document = dictionary.build_dictionary(connection)
    odd = next(t for t in document["tables"] if t["name"] == 'Odd"Name')
    assert odd["description"] is None
    assert all(column["description"] is None for column in odd["columns"])
