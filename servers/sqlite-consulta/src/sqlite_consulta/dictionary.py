"""Schema and data dictionary documents, served as MCP resources."""

import json
import sqlite3
from importlib import resources
from typing import TypedDict, cast

from sqlite_consulta import database

SCHEMA_URI = "sqlite-consulta://schema"
DICTIONARY_URI = "sqlite-consulta://dictionary"
_DICTIONARY_FILE = "data_dictionary.json"


class _TableSource(TypedDict):
    description: str
    columns: dict[str, str]


class _DictionarySource(TypedDict):
    database: str
    tables: dict[str, _TableSource]


class SchemaDocument(TypedDict):
    """The schema of the database, as read from SQLite."""

    dialect: str
    tables: list[database.TableSchema]


class DictionaryColumn(TypedDict):
    """A column of the data dictionary."""

    name: str
    type: str
    description: str | None
    sensitive: bool


class DictionaryTable(TypedDict):
    """A table of the data dictionary."""

    name: str
    description: str | None
    row_count: int
    columns: list[DictionaryColumn]
    foreign_keys: list[database.ForeignKeyInfo]


class DictionaryDocument(TypedDict):
    """The data dictionary: schema facts plus the versioned descriptions."""

    database: str
    sensitive_columns_note: str
    tables: list[DictionaryTable]


SENSITIVE_NOTE = (
    "Columns with sensitive=true are returned as '***' and cannot be used in WHERE, JOIN, "
    "GROUP BY, HAVING, ORDER BY, LIMIT, or OFFSET."
)


def load_source() -> _DictionarySource:
    """Read the versioned descriptions that ship inside the package.

    Returns:
        The descriptions of the database, its tables, and its columns.
    """
    text = resources.files("sqlite_consulta").joinpath(_DICTIONARY_FILE).read_text("utf-8")
    return cast("_DictionarySource", json.loads(text))


def build_schema(connection: sqlite3.Connection) -> SchemaDocument:
    """Build the schema document from the live database.

    Args:
        connection: Open database connection.

    Returns:
        Every table with its columns and foreign keys.
    """
    names = [table["name"] for table in database.list_tables(connection)]
    return SchemaDocument(
        dialect="SQLite",
        tables=[database.describe_table(connection, name) for name in names],
    )


def build_dictionary(connection: sqlite3.Connection) -> DictionaryDocument:
    """Build the data dictionary: live schema facts joined with the descriptions.

    Tables or columns without a description are still listed, with a null
    description, so a schema change never hides data.

    Args:
        connection: Open database connection.

    Returns:
        The data dictionary.
    """
    source = load_source()
    tables: list[DictionaryTable] = []
    for info in database.list_tables(connection):
        schema = database.describe_table(connection, info["name"])
        described = source["tables"].get(info["name"])
        column_text = described["columns"] if described else {}
        tables.append(
            DictionaryTable(
                name=info["name"],
                description=described["description"] if described else None,
                row_count=info["row_count"],
                columns=[
                    DictionaryColumn(
                        name=column["name"],
                        type=column["type"],
                        description=column_text.get(column["name"]),
                        sensitive=column["sensitive"],
                    )
                    for column in schema["columns"]
                ],
                foreign_keys=schema["foreign_keys"],
            )
        )
    return DictionaryDocument(
        database=source["database"], sensitive_columns_note=SENSITIVE_NOTE, tables=tables
    )
