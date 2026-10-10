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

import json
import re
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
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
MAX_SQL_LENGTH = 5_000
MAX_VALUE_LENGTH = 2_000
"""Maximum size of any SQLite value, in bytes.

The progress handler only runs between VM instructions, and some functions
(``like``, ``instr``, ``replace``, ``trim``) cost O(n * m) inside a single
instruction. Keeping every value small bounds that cost, so the timeout holds.
"""
MAX_LIKE_PATTERN_LENGTH = 50
MAX_COLUMNS = 100
MAX_RESULT_CHARS = 200_000
"""Size cap of the rows serialized as JSON; rows beyond it are cut (``truncated``)."""
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
        table_aliases: Pairs of (alias, table), lowercase, for every table reference.
    """

    sql: str
    masked_positions: frozenset[int]
    table_aliases: tuple[tuple[str, str], ...] = ()


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
        return _validate(sql, schema)
    except RecursionError:
        raise _reject("The query is too deeply nested.") from None


def _validate(sql: str, schema: Schema) -> ValidatedQuery:
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
    aliases = tuple(
        sorted(
            {
                (node.alias_or_name.lower(), node.name.lower())
                for node in qualified.find_all(exp.Table)
                if node.name.lower() in tables
            }
        )
    )
    return ValidatedQuery(
        sql=qualified.sql(dialect="sqlite"),
        masked_positions=frozenset(index for index, taint in enumerate(tainted) if taint),
        table_aliases=aliases,
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
        connection.setlimit(sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, MAX_LIKE_PATTERN_LENGTH)
        connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, MAX_COLUMNS)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_LENGTH * 4)
        connection.set_authorizer(_authorizer(tables))
        yield connection


def _translate_error(error: sqlite3.Error) -> QueryRejectedError | QueryFailedError:
    message = str(error)
    if message == "interrupted":
        return QueryRejectedError("limits", "Query exceeded the time limit.")
    if (
        message.startswith("not authorized")
        or message.endswith("is prohibited")
        or message == "authorization denied"
    ):
        return QueryRejectedError("authorizer", f"Blocked by the authorizer: {message}.")
    if "too big" in message:
        return QueryRejectedError(
            "limits", f"A value exceeded the size limit of {MAX_VALUE_LENGTH} bytes."
        )
    if message.startswith("LIKE or GLOB pattern too complex"):
        return QueryRejectedError(
            "limits", f"LIKE/GLOB patterns are limited to {MAX_LIKE_PATTERN_LENGTH} characters."
        )
    if message.startswith("too many columns"):
        return QueryRejectedError("limits", f"Results are limited to {MAX_COLUMNS} columns.")
    if "readonly" in message or "query_only" in message:
        return QueryRejectedError("read_only", "The database is read-only.")
    return QueryFailedError(f"The query failed: {message}.")


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
        raise _translate_error(error) from None
    finally:
        connection.set_progress_handler(None, 0)
    return columns, fetched[: limits.max_rows], len(fetched) > limits.max_rows


def _plan_rows(connection: sqlite3.Connection, sql: str) -> list[tuple[int, int, str]]:
    try:
        cursor = connection.execute("EXPLAIN QUERY PLAN " + sql)
        return [(int(row[0]), int(row[1]), str(row[3])) for row in cursor.fetchall()]
    except sqlite3.Error as error:
        raise _translate_error(error) from None


_SCAN = re.compile(r"SCAN (\S+)")
_SEARCH = re.compile(
    r"SEARCH (?P<alias>\S+) USING (?:(?P<pk>INTEGER PRIMARY KEY)|(?:AUTOMATIC )?(?:COVERING )?"
    r"INDEX ?(?P<index>\S+)?) ?\((?P<terms>[^()]*)\)$"
)
_IN_OPERATOR = re.compile(r".*ON TABLE (\S+) FOR IN-OPERATOR")
_FIRST_COLUMN = re.compile(r"(\w+)\s*=")
UNBOUNDED_COST = 10**12 + 1
"""Cost given to plans without a known size, such as recursive CTEs: always confirmed."""
_ROUTINE = re.compile(r"(?:CO-ROUTINE|MATERIALIZE) (\S+)")


type Fanout = Callable[[str, str | None, str, int], int]
"""Rows per equality lookup: (table, index or None, first column, equality terms) -> rows."""


def equality_fanout(connection: sqlite3.Connection, schema: Schema) -> Fanout:
    """Build a function that estimates rows per equality lookup on an index.

    A unique index matches one row only when the equality terms cover all of
    its columns; a lookup by a prefix of a composite unique index does not. Otherwise the estimate
    is the size of the largest group of equal values in the column (the worst
    key), which catches joins on low-cardinality or skewed foreign keys.

    Args:
        connection: A plain read-only connection (not the guarded one).
        schema: Tables and columns, used to validate names taken from the plan.

    Returns:
        The estimating function, with results cached.
    """
    tables = {name.lower(): name for name in schema}
    columns = {
        name.lower(): {column.lower(): column for column in cols} for name, cols in schema.items()
    }
    cache: dict[tuple[str, str | None, str, int], int] = {}

    def fanout(table: str, index: str | None, column: str, terms: int) -> int:
        key = (table.lower(), index, column.lower(), terms)
        if key in cache:
            return cache[key]
        real_table = tables.get(key[0])
        real_column = columns.get(key[0], {}).get(key[2])
        if real_table is None or real_column is None:
            cache[key] = 1
            return 1
        unique = index is not None and connection.execute(
            'SELECT "unique" FROM pragma_index_list(?) WHERE name = ?', (real_table, index)
        ).fetchone() == (1,)
        if unique:
            (width,) = connection.execute(
                "SELECT count(*) FROM pragma_index_info(?)", (index,)
            ).fetchone()
            unique = terms >= int(width)
        if unique:
            cache[key] = 1
            return 1
        quoted_table = '"' + real_table.replace('"', '""') + '"'
        quoted_column = '"' + real_column.replace('"', '""') + '"'
        # Names come from the schema and are quoted, never from the client.
        (largest,) = connection.execute(
            f"SELECT max(n) FROM (SELECT count(*) AS n FROM {quoted_table} "  # noqa: S608
            f"GROUP BY {quoted_column})"
        ).fetchone()
        cache[key] = max(1, int(largest or 1))
        return cache[key]

    return fanout


def estimate_cost(
    connection: sqlite3.Connection,
    validated: ValidatedQuery,
    row_counts: Mapping[str, int],
    fanout: Fanout | None = None,
) -> int:
    """Estimate how many rows a query will examine, from SQLite's query plan.

    Full scans of a table cost its row count, and nested scans multiply. Index
    searches by equality count as the rows per key (see `equality_fanout`;
    one row when no fanout function is given); range searches (``>``, ``<``,
    ``BETWEEN``) count as the whole table; an ``IN`` list counts as the size of
    the table that feeds it. Recursive CTEs have no
    known size and get `UNBOUNDED_COST`. A correlated subquery runs once per
    outer row, so its cost is multiplied by the outer loops. This is an
    approximation used to decide when to ask for confirmation, not a guarantee:
    the timeout and the size limits still apply to every query.

    Args:
        connection: A connection from `guarded_connection`.
        validated: The validated query.
        row_counts: Row count of each table, keyed by lowercase table name.
        fanout: Rows per equality lookup; see `equality_fanout`.

    Returns:
        The estimated number of rows examined.

    Raises:
        QueryRejectedError: If SQLite blocks the plan (for example, the authorizer).
        QueryFailedError: If SQLite cannot plan the query.
    """
    aliases: dict[str, int] = {}
    alias_tables: dict[str, str] = {}
    for alias, table in validated.table_aliases:
        if row_counts.get(table, 0) >= aliases.get(alias, 0):
            alias_tables[alias] = table
        aliases[alias] = max(aliases.get(alias, 0), row_counts.get(table, 0))
    children: dict[int, list[tuple[int, str]]] = {}
    for node_id, parent_id, detail in _plan_rows(connection, validated.sql):
        children.setdefault(parent_id, []).append((node_id, detail))

    if any(detail == "RECURSIVE STEP" for rows in children.values() for _, detail in rows):
        return UNBOUNDED_COST
    sizes: dict[str, int] = {}

    def unknown_size() -> int:
        # A CTE or subquery read through an alias: no statistics, so assume it is as
        # large as the largest known source. Never 1.
        return max([*sizes.values(), *row_counts.values(), 1])

    def scan_size(detail: str) -> int:
        in_operator = _IN_OPERATOR.match(detail)
        if in_operator is not None:
            return row_counts.get(in_operator.group(1).strip('"').lower(), 1) or 1
        search = _SEARCH.match(detail)
        if search is not None:
            name = search.group("alias").strip('"').lower()
            terms = search.group("terms")
            if "<" in terms or ">" in terms:
                return aliases.get(name) or row_counts.get(name) or 1
            if search.group("pk") or fanout is None:
                return 1
            table = alias_tables.get(name)
            if table is None:
                return unknown_size()
            first = _FIRST_COLUMN.search(terms)
            if first is None:
                return aliases.get(name) or 1
            count = len(_FIRST_COLUMN.findall(terms))
            return fanout(table, search.group("index"), first.group(1), count)
        match = _SCAN.match(detail)
        if match is None or detail.startswith("SCAN CONSTANT ROW"):
            return 1
        name = match.group(1).strip('"').lower()
        return aliases.get(name) or row_counts.get(name) or sizes.get(name) or unknown_size()

    def or_branches(node_id: int) -> int:
        # MULTI-INDEX OR runs one lookup per branch for each outer row: sum the branches.
        total = 0
        for branch_id, _ in children.get(node_id, []):
            for _, detail in children.get(branch_id, []):
                total += scan_size(detail)
        return max(total, 1)

    def loops(parent_id: int) -> int:
        product = 1
        for node_id, detail in children.get(parent_id, []):
            if detail == "MULTI-INDEX OR":
                product *= or_branches(node_id)
            else:
                product *= scan_size(detail)
        return product

    for rows in children.values():
        for node_id, detail in rows:
            routine = _ROUTINE.match(detail)
            if routine is not None:
                sizes[routine.group(1).strip('"').lower()] = loops(node_id)

    def group_cost(parent_id: int, multiplier: int) -> int:
        own = loops(parent_id)
        total = own * multiplier
        for node_id, detail in children.get(parent_id, []):
            if detail == "MULTI-INDEX OR":
                continue  # already counted in `loops`
            inner = multiplier * own if detail.startswith("CORRELATED") else multiplier
            total += group_cost(node_id, inner)
        return total

    return group_cost(0, 1)


@dataclass(frozen=True)
class PreparedQuery:
    """A validated query with its estimated cost.

    Attributes:
        validated: The query that passed the AST layer.
        estimated_cost: Estimated number of rows examined (see `estimate_cost`).
    """

    validated: ValidatedQuery
    estimated_cost: int


def prepare_query(path: Path, sql: str) -> PreparedQuery:
    """Validate a query and estimate its cost, without running it.

    Args:
        path: Path of the database file.
        sql: SQL sent by the client.

    Returns:
        The prepared query.

    Raises:
        QueryRejectedError: If any layer blocks the query.
        QueryFailedError: If SQLite cannot plan an allowed query.
    """
    with closing(database.connect_read_only(path)) as connection:
        schema = load_schema(connection)
        row_counts = {t["name"].lower(): t["row_count"] for t in database.list_tables(connection)}
    validated = validate(sql, schema)
    tables = frozenset(name.lower() for name in schema)
    with (
        closing(database.connect_read_only(path)) as plain,
        guarded_connection(path, tables) as connection,
    ):
        cost = estimate_cost(connection, validated, row_counts, equality_fanout(plain, schema))
    return PreparedQuery(validated=validated, estimated_cost=cost)


def run_prepared(path: Path, prepared: PreparedQuery, limits: Limits | None = None) -> QueryResult:
    """Run a prepared query through the inner layers and mask the result.

    Args:
        path: Path of the database file.
        prepared: A query from `prepare_query`.
        limits: Execution limits; defaults to `Limits()`.

    Returns:
        The rows, with sensitive output columns masked.

    Raises:
        QueryRejectedError: If an inner layer blocks the query.
        QueryFailedError: If SQLite cannot run an allowed query.
    """
    limits = limits or Limits()
    validated = prepared.validated
    with closing(database.connect_read_only(path)) as connection:
        tables = frozenset(t["name"].lower() for t in database.list_tables(connection))
    with guarded_connection(path, tables) as connection:
        columns, fetched, truncated = execute(connection, validated.sql, limits)
    masked = validated.masked_positions
    rows: list[list[database.CellValue]] = []
    size = 0
    for raw in fetched:
        row = [
            database.MASK if index in masked else database.to_cell(value)
            for index, value in enumerate(raw)
        ]
        size += len(json.dumps(row))
        if size > MAX_RESULT_CHARS:
            truncated = True
            break
        rows.append(row)
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        masked_columns=[name for index, name in enumerate(columns) if index in masked],
        executed_sql=validated.sql,
        notice=UNTRUSTED_DATA_NOTICE,
    )


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
    return run_prepared(path, prepare_query(path, sql), limits)
