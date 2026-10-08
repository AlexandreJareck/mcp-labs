"""Validate and run free-form SQL safely, in layers (Design Doc 0001, phase 2).

Layers, from outside in:

1. ``ast``: `sqlglot` parses the SQL; only a single read-only query over known
   tables and allowed functions passes. Sensitive columns may appear only in
   the output, never in filters, joins, grouping, or ordering.
2. ``read_only``: the connection is opened with ``mode=ro`` and ``query_only``.
3. ``authorizer``: SQLite asks `set_authorizer` before every operation; only
   reads of known tables and allowed functions pass, and reads of sensitive
   columns return NULL.
4. ``limits``: a progress handler interrupts the query at the timeout, at most
   ``max_rows`` rows are fetched, and SQLite length limits cap values.
5. ``masking``: output columns derived from sensitive columns are replaced by
   ``***``.

The SQL executed is the one regenerated from the validated AST, so what runs is
exactly what was analyzed.
"""

import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify

from sqlite_consulta import database

type Layer = Literal["ast", "read_only", "authorizer", "limits", "masking"]

DEFAULT_TIMEOUT_MS = 2000
DEFAULT_MAX_ROWS = 200
MAX_SQL_LENGTH = 10_000
MAX_VALUE_LENGTH = 100_000
MAX_CELL_CHARS = 2_000
PROGRESS_HANDLER_STEPS = 1_000

ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Aggregates.
        "avg", "count", "group_concat", "max", "min", "string_agg", "sum", "total",
        # Scalar functions without side effects or unbounded output.
        "abs", "coalesce", "glob", "ifnull", "iif", "instr", "length", "like", "lower",
        "ltrim", "nullif", "replace", "round", "rtrim", "substr", "substring", "trim",
        "typeof", "upper",
        # Date and time.
        "date", "datetime", "julianday", "strftime", "time", "unixepoch",
        # Window functions.
        "cume_dist", "dense_rank", "first_value", "lag", "last_value", "lead",
        "nth_value", "ntile", "percent_rank", "rank", "row_number",
    }
)  # fmt: skip
"""Functions allowed by name, lowercase. Everything else is denied by the authorizer.

Notably absent: ``load_extension``, ``randomblob``, ``zeroblob``, ``printf`` and
``format`` (unbounded output), and the ``sqlite_*`` introspection functions.
"""

_FORBIDDEN_NODES: tuple[type[exp.Expr], ...] = (
    exp.DML,
    exp.DDL,
    exp.Alter,
    exp.Analyze,
    exp.Attach,
    exp.Command,
    exp.Commit,
    exp.Detach,
    exp.Drop,
    exp.Into,
    exp.Pragma,
    exp.Rollback,
    exp.Set,
    exp.Transaction,
)

UNTRUSTED_DATA_NOTICE = database.UNTRUSTED_DATA_NOTICE


class QueryRejectedError(Exception):
    """A query was blocked by one of the protection layers.

    Attributes:
        layer: The layer that blocked the query.
        reason: A message safe to show to the client (never contains data).
    """

    def __init__(self, layer: Layer, reason: str) -> None:
        """Create the error.

        Args:
            layer: The layer that blocked the query.
            reason: A message safe to show to the client.
        """
        super().__init__(reason)
        self.layer: Layer = layer
        self.reason = reason


class QueryFailedError(Exception):
    """A query passed every layer but SQLite could not run it (for example, a type error)."""


@dataclass(frozen=True)
class ValidatedQuery:
    """A query that passed the AST layer.

    Attributes:
        sql: SQL regenerated from the qualified AST; this is what runs.
        masked_positions: Output positions derived from sensitive columns.
    """

    sql: str
    masked_positions: frozenset[int]


@dataclass(frozen=True)
class Limits:
    """Execution limits.

    Attributes:
        timeout_ms: Maximum execution time, in milliseconds.
        max_rows: Maximum number of rows returned.
    """

    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_rows: int = DEFAULT_MAX_ROWS


class QueryResult(TypedDict):
    """Rows returned by a query, with sensitive columns masked."""

    columns: list[str]
    rows: list[list[database.CellValue]]
    row_count: int
    truncated: bool
    masked_columns: list[str]
    executed_sql: str
    notice: str


type Schema = dict[str, dict[str, str]]


def load_schema(connection: sqlite3.Connection) -> Schema:
    """Read table and column names of the user tables.

    Args:
        connection: Open database connection.

    Returns:
        Mapping of table name to column names (types are not needed).
    """
    return {
        table["name"]: {
            column["name"]: "TEXT"
            for column in database.describe_table(connection, table["name"])["columns"]
        }
        for table in database.list_tables(connection)
    }


# --- Layer 1: AST -----------------------------------------------------------


@dataclass
class _Derived:
    """Output column names of a subquery or CTE and whether each is sensitive."""

    names: list[str]
    tainted: list[bool]

    def is_tainted(self, column: str) -> bool:
        return any(
            taint for name, taint in zip(self.names, self.tainted, strict=True) if name == column
        )


@dataclass
class _Env:
    """Name resolution for one SELECT: its sources, CTEs, and the enclosing query."""

    tables: dict[str, str]
    sources: dict[str, str | _Derived] = field(default_factory=dict)
    ctes: dict[str, _Derived] = field(default_factory=dict)
    aliases: dict[str, bool] = field(default_factory=dict)
    parent: "_Env | None" = None

    def find_cte(self, name: str) -> _Derived | None:
        env: _Env | None = self
        while env is not None:
            if name in env.ctes:
                return env.ctes[name]
            env = env.parent
        return None

    def column_tainted(self, column: exp.Column) -> bool:
        # An unqualified column in ORDER BY or GROUP BY may name an output alias.
        if not column.table and column.name in self.aliases:
            return self.aliases[column.name]
        env: _Env | None = self
        while env is not None:
            source = env.sources.get(column.table)
            if isinstance(source, str):
                return database.is_sensitive(source, column.name)
            if isinstance(source, _Derived):
                return source.is_tainted(column.name)
            env = env.parent
        # Unresolvable references are treated as sensitive (fail safe).
        return True

    def child(self) -> "_Env":
        return _Env(tables=self.tables, parent=self)


def _reject(reason: str) -> QueryRejectedError:
    return QueryRejectedError("ast", reason)


def _expr_tainted(node: exp.Expr, env: _Env) -> bool:
    if isinstance(node, exp.Column):
        return env.column_tainted(node)
    if isinstance(node, exp.Subquery):
        return any(_analyze_query(node.this, env.child()))
    if isinstance(node, exp.Query):
        return any(_analyze_query(node, env.child()))
    return any(_expr_tainted(child, env) for child in node.iter_expressions())


def _output_names(query: exp.Query) -> list[str]:
    return list(query.named_selects)


def _set_aliases(env: _Env, names: list[str], tainted: list[bool]) -> None:
    for name, taint in zip(names, tainted, strict=False):
        env.aliases[name] = env.aliases.get(name, False) or taint


def _analyze_ctes(with_: exp.With | None, env: _Env) -> None:
    if with_ is None:
        return
    for cte in with_.expressions:
        name = cte.alias_or_name
        body = cte.this
        declared = list(cte.alias_column_names)
        names = declared or _output_names(body)
        # Recursive CTEs reference themselves: iterate until the taint is stable.
        env.ctes[name] = _Derived(names=names, tainted=[False] * len(names))
        for _ in range(len(names) + 1):
            tainted = _analyze_query(body, env.child())
            if tainted == env.ctes[name].tainted:
                break
            env.ctes[name] = _Derived(names=names, tainted=tainted)


def _register_source(source: exp.Expr, env: _Env) -> None:
    alias = source.alias_or_name
    if isinstance(source, exp.Subquery):
        derived_names = _output_names(source.this)
        env.sources[alias] = _Derived(derived_names, _analyze_query(source.this, env.child()))
        return
    if not isinstance(source, exp.Table) or not isinstance(source.this, exp.Identifier):
        raise _reject("Only tables, subqueries, and CTEs are allowed in FROM and JOIN.")
    if source.args.get("db") or source.args.get("catalog"):
        raise _reject("Schema-qualified table names are not allowed.")
    cte = env.find_cte(source.name)
    if cte is not None:
        env.sources[alias] = cte
        return
    if source.name not in env.tables:
        raise _reject("Unknown table. Call list_tables to see the valid names.")
    env.sources[alias] = env.tables[source.name]


def _analyze_select(select: exp.Select, env: _Env) -> list[bool]:
    _analyze_ctes(select.args.get("with_"), env)
    from_ = select.args.get("from_")
    if from_ is not None:
        _register_source(from_.this, env)
    for join in select.args.get("joins") or []:
        _register_source(join.this, env)

    if any(isinstance(projection, exp.Star) for projection in select.expressions):
        raise _reject("Could not expand '*'. Check the table names.")
    tainted = [_expr_tainted(projection, env) for projection in select.expressions]
    _set_aliases(env, _output_names(select), tainted)

    for key, value in select.args.items():
        if key in {"expressions", "with_", "from_"} or value is None:
            continue
        parts = value if isinstance(value, list) else [value]
        for part in parts:
            for node in _checked_nodes(part):
                if _expr_tainted(node, env):
                    raise _reject(
                        "Sensitive columns cannot be used in filters, joins, grouping, or ordering."
                    )
    return tainted


def _checked_nodes(part: object) -> list[exp.Expr]:
    if not isinstance(part, exp.Expr):
        return []
    if not isinstance(part, exp.Join):
        return [part]
    # The joined source was registered already; only its condition is checked.
    # `qualify` rewrites JOIN ... USING into an ON condition.
    condition = part.args.get("on")
    return [condition] if isinstance(condition, exp.Expr) else []


def _analyze_query(query: exp.Expr, env: _Env) -> list[bool]:
    if isinstance(query, exp.Subquery):
        return _analyze_query(query.this, env)
    if isinstance(query, exp.SetOperation):
        _analyze_ctes(query.args.get("with_"), env)
        left = _analyze_query(query.left, env.child())
        right = _analyze_query(query.right, env.child())
        if len(left) != len(right):
            raise _reject("Both sides of a set operation must have the same number of columns.")
        tainted = [a or b for a, b in zip(left, right, strict=True)]
        _set_aliases(env, _output_names(query), tainted)
        for key in ("order", "limit", "offset"):
            node = query.args.get(key)
            if node is not None and _expr_tainted(node, env):
                raise _reject("Sensitive columns cannot be used in ordering.")
        return tainted
    if isinstance(query, exp.Select):
        return _analyze_select(query, env)
    raise _reject("Only SELECT queries are allowed.")


def validate(sql: str, schema: Schema) -> ValidatedQuery:
    """Run the AST layer: accept a single safe SELECT and compute output masking.

    Args:
        sql: SQL sent by the client.
        schema: Tables and columns of the database (see `load_schema`).

    Returns:
        The SQL to execute and the output positions to mask.

    Raises:
        QueryRejectedError: If the query is not allowed (layer ``ast``).
    """
    if len(sql) > MAX_SQL_LENGTH:
        raise _reject(f"SQL longer than {MAX_SQL_LENGTH} characters.")
    try:
        statements = [tree for tree in sqlglot.parse(sql, read="sqlite") if tree is not None]
    except SqlglotError:
        raise _reject("The SQL could not be parsed.") from None
    if len(statements) != 1:
        raise _reject("Exactly one statement is allowed.")
    tree = statements[0]
    if isinstance(tree, exp.Subquery):
        raise _reject("Remove the parentheses around the whole query.")
    if not isinstance(tree, exp.Query):
        raise _reject("Only SELECT queries are allowed.")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise _reject("Only read-only SELECT queries are allowed.")
        # Functions unknown to sqlglot; known ones are checked by the authorizer.
        if isinstance(node, exp.Anonymous) and str(node.name).lower() not in ALLOWED_FUNCTIONS:
            raise _reject("Function not allowed.")

    qualify_schema: dict[str, object] = dict(schema)
    try:
        qualified = qualify(
            tree,
            schema=qualify_schema,
            dialect="sqlite",
            validate_qualify_columns=True,
            identify=True,
        )
    except OptimizeError:
        raise _reject("Unknown column or ambiguous reference.") from None
    tables = {name.lower(): name.lower() for name in schema}
    tainted = _analyze_query(qualified, _Env(tables=tables))
    return ValidatedQuery(
        sql=qualified.sql(dialect="sqlite"),
        masked_positions=frozenset(index for index, taint in enumerate(tainted) if taint),
    )


# --- Layers 2 to 4: connection, authorizer, limits ---------------------------


def _authorizer(
    tables: frozenset[str],
) -> Callable[[int, str | None, str | None, str | None, str | None], int]:
    def authorize(
        action: int, arg1: str | None, arg2: str | None, db: str | None, _trigger: str | None
    ) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # Reads of CTEs and subqueries have no database name; real tables do.
            if db is None:
                return sqlite3.SQLITE_OK
            if arg1 is None or arg1.lower() not in tables:
                return sqlite3.SQLITE_DENY
            if arg2 and database.is_sensitive(arg1, arg2):
                return sqlite3.SQLITE_IGNORE
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if arg2 is not None and arg2.lower() in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return authorize


@contextmanager
def guarded_connection(path: Path, tables: frozenset[str]) -> Iterator[sqlite3.Connection]:
    """Open a read-only connection with the authorizer and SQLite limits installed.

    Args:
        path: Path of the database file.
        tables: Lowercase names of the tables that may be read.

    Yields:
        The guarded connection; it is closed on exit.
    """
    with closing(database.connect_read_only(path)) as connection:
        connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_LENGTH)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_LENGTH * 4)
        connection.set_authorizer(_authorizer(tables))
        yield connection


def execute(
    connection: sqlite3.Connection, sql: str, limits: Limits
) -> tuple[list[str], list[tuple[database.CellValue | bytes, ...]], bool]:
    """Run SQL on a guarded connection under the time and row limits.

    It does not validate the SQL: callers must pass SQL from `validate`. It is
    public so tests can exercise the inner layers on their own.

    Args:
        connection: A connection from `guarded_connection`.
        sql: SQL to run.
        limits: Execution limits.

    Returns:
        Column names, up to ``limits.max_rows`` rows, and whether rows were cut.

    Raises:
        QueryRejectedError: If an inner layer blocks the query.
        QueryFailedError: If SQLite fails for another reason.
    """
    deadline = time.monotonic() + limits.timeout_ms / 1000
    connection.set_progress_handler(
        lambda: int(time.monotonic() > deadline), PROGRESS_HANDLER_STEPS
    )
    try:
        cursor = connection.execute(sql)
        columns = [str(description[0]) for description in cursor.description]
        fetched = cursor.fetchmany(limits.max_rows + 1)
    except sqlite3.Error as error:
        message = str(error)
        if message == "interrupted":
            raise QueryRejectedError("limits", "Query exceeded the time limit.") from None
        if (
            message.startswith("not authorized")
            or message.endswith("is prohibited")
            or message == "authorization denied"
        ):
            raise QueryRejectedError(
                "authorizer", f"Blocked by the authorizer: {message}."
            ) from None
        if "too big" in message:
            raise QueryRejectedError("limits", "A value exceeded the size limit.") from None
        if "readonly" in message or "query_only" in message:
            raise QueryRejectedError("read_only", "The database is read-only.") from None
        raise QueryFailedError(f"The query failed: {message}.") from None
    finally:
        connection.set_progress_handler(None, 0)
    return columns, fetched[: limits.max_rows], len(fetched) > limits.max_rows


def _cell(value: database.CellValue | bytes) -> database.CellValue:
    cell = database.to_cell(value)
    if isinstance(cell, str) and len(cell) > MAX_CELL_CHARS:
        return cell[:MAX_CELL_CHARS] + "...[truncated]"
    return cell


def run_query(path: Path, sql: str, limits: Limits | None = None) -> QueryResult:
    """Validate and run a query through every protection layer.

    Args:
        path: Path of the database file.
        sql: SQL sent by the client.
        limits: Execution limits; defaults to `Limits()`.

    Returns:
        The rows, with sensitive output columns masked.

    Raises:
        QueryRejectedError: If any layer blocks the query.
        QueryFailedError: If SQLite cannot run an allowed query.
    """
    limits = limits or Limits()
    with closing(database.connect_read_only(path)) as connection:
        schema = load_schema(connection)
    validated = validate(sql, schema)
    tables = frozenset(name.lower() for name in schema)
    with guarded_connection(path, tables) as connection:
        columns, rows, truncated = execute(connection, validated.sql, limits)
    masked = validated.masked_positions
    return QueryResult(
        columns=columns,
        rows=[
            [database.MASK if index in masked else _cell(value) for index, value in enumerate(row)]
            for row in rows
        ],
        row_count=len(rows),
        truncated=truncated,
        masked_columns=[name for index, name in enumerate(columns) if index in masked],
        executed_sql=validated.sql,
        notice=UNTRUSTED_DATA_NOTICE,
    )
