"""Attack suite: malicious SQL and the layer that blocks each case.

``blocked_by`` is the first layer that stops the attack in the full pipeline
(`run_query`). ``backstops`` lists inner layers that still stop it when the
outer ones are bypassed, so a bug in one layer does not open a hole:

- ``driver``: Python's `sqlite3` runs only one statement per `execute()`.
- ``authorizer``: `set_authorizer` denies the operation.
- ``read_only``: with the authorizer removed, the read-only connection refuses
  the write.
- ``nulls``: with the AST layer bypassed, the authorizer turns sensitive
  columns into NULL, so no sensitive value comes back (the query may return
  meaningless rows or fail, as ``LIMIT NULL`` does).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from sqlite_consulta.query import (
    Layer,
    Limits,
    QueryFailedError,
    QueryRejectedError,
    execute,
    guarded_connection,
    run_query,
)

type Backstop = Literal["driver", "authorizer", "read_only", "nulls"]

FAST = Limits(timeout_ms=200, max_rows=50)
TABLES = frozenset({"album", "artist", "customer", "employee", "invoice", 'odd"name'})


@dataclass(frozen=True)
class Attack:
    id: str
    sql: str
    blocked_by: Layer
    backstops: tuple[Backstop, ...] = ()


ATTACKS: tuple[Attack, ...] = (
    # Injection and stacked statements.
    Attack("stacked_drop", "SELECT 1; DROP TABLE Artist", "ast", ("driver",)),
    Attack(
        "stacked_after_quote",
        "SELECT Name FROM Artist WHERE Name = 'x'; DELETE FROM Artist; --",
        "ast",
        ("driver",),
    ),
    Attack(
        "tautology_then_update",
        "SELECT Name FROM Artist WHERE ArtistId = 1 OR 1 = 1; UPDATE Artist SET Name = 'x'",
        "ast",
        ("driver",),
    ),
    Attack("transaction", "BEGIN; DELETE FROM Artist; COMMIT", "ast", ("authorizer",)),
    # Writes and DDL.
    Attack("delete", "DELETE FROM Artist", "ast", ("authorizer", "read_only")),
    Attack("update", "UPDATE Artist SET Name = 'x'", "ast", ("authorizer", "read_only")),
    Attack("insert", "INSERT INTO Artist (Name) VALUES ('x')", "ast", ("authorizer", "read_only")),
    Attack("replace", "REPLACE INTO Artist VALUES (1, 'x')", "ast", ("authorizer", "read_only")),
    Attack("drop_table", "DROP TABLE Artist", "ast", ("authorizer", "read_only")),
    Attack("create_table", "CREATE TABLE evil (x)", "ast", ("authorizer", "read_only")),
    Attack(
        "alter_table", "ALTER TABLE Artist ADD COLUMN x TEXT", "ast", ("authorizer", "read_only")
    ),
    Attack("create_temp_view", "CREATE TEMP VIEW v AS SELECT 1", "ast", ("authorizer",)),
    # Writes disguised as reads.
    Attack("delete_in_cte", "WITH d AS (DELETE FROM Artist RETURNING *) SELECT * FROM d", "ast"),
    Attack(
        "insert_select",
        "INSERT INTO Artist SELECT * FROM Artist",
        "ast",
        ("authorizer", "read_only"),
    ),
    Attack(
        "comment_prefixed_delete",
        "/* monthly report */ DELETE FROM Artist",
        "ast",
        ("authorizer", "read_only"),
    ),
    Attack("mixed_case_delete", "dElEtE fRoM Artist", "ast", ("authorizer", "read_only")),
    Attack("vacuum_into", "VACUUM INTO 'attack-copy.db'", "ast", ("authorizer",)),
    # PRAGMA, ATTACH, and internal tables.
    Attack("pragma_query_only_off", "PRAGMA query_only = OFF", "ast", ("authorizer",)),
    Attack("pragma_writable_schema", "PRAGMA writable_schema = ON", "ast", ("authorizer",)),
    Attack(
        "pragma_table_function",
        "SELECT * FROM pragma_table_info('Customer')",
        "ast",
        ("authorizer",),
    ),
    Attack("attach", "ATTACH DATABASE 'attack.db' AS evil", "ast", ("authorizer",)),
    Attack("detach", "DETACH DATABASE main", "ast", ("authorizer",)),
    Attack("sqlite_master", "SELECT * FROM sqlite_master", "ast", ("authorizer",)),
    Attack("sqlite_schema_sql", "SELECT sql FROM sqlite_schema", "ast", ("authorizer",)),
    Attack("temp_schema", "SELECT * FROM temp.sqlite_master", "ast", ("authorizer",)),
    Attack("schema_qualified", "SELECT Email FROM main.Customer", "ast", ("nulls",)),
    # Dangerous functions.
    Attack("load_extension", "SELECT load_extension('evil')", "ast", ("authorizer",)),
    Attack("randomblob", "SELECT randomblob(1000000000)", "ast", ("authorizer",)),
    Attack("zeroblob", "SELECT zeroblob(1000000000)", "ast", ("authorizer",)),
    Attack("printf_width", "SELECT printf('%.*c', 1000000000, 'x')", "ast", ("authorizer",)),
    Attack("readfile", "SELECT readfile('C:/Windows/win.ini')", "ast"),
    Attack("format_known_to_parser", "SELECT format('%s', Name) FROM Artist", "authorizer"),
    Attack("hex_known_to_parser", "SELECT hex(Name) FROM Artist", "authorizer"),
    Attack("sqlite_version", "SELECT sqlite_version()", "authorizer"),
    Attack("json_function", "SELECT json_extract('{}', '$.a')", "authorizer"),
    # Expensive queries.
    Attack(
        "cross_join",
        "SELECT count(*) FROM Artist a, Artist b, Artist c, Artist d, Artist e, Artist f, "
        "Artist g, Artist h, Artist i",
        "limits",
    ),
    Attack(
        "infinite_recursion",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r",
        "limits",
    ),
    Attack(
        "string_explosion",
        "WITH RECURSIVE r(s) AS (SELECT 'xxxxxxxxxx' UNION ALL SELECT s || s FROM r) "
        "SELECT max(length(s)) FROM r",
        "limits",
    ),
    Attack("huge_sql", "SELECT 1" + " " * 20_000, "ast"),
    Attack(
        "like_pattern_backtracking",
        "WITH RECURSIVE p(q, n) AS (SELECT '%', 1 UNION ALL SELECT q || 'a_', n + 1 FROM p "
        "WHERE n < 100) SELECT Name LIKE (SELECT max(q) FROM p) || 'b' AS x FROM Artist",
        "limits",
    ),
    Attack(
        "long_text_for_quadratic_functions",
        "WITH RECURSIVE t(a, n) AS (SELECT 'a', 1 UNION ALL SELECT a || 'a', n + 1 FROM t "
        "WHERE n < 40000) SELECT instr(max(a), 'b') AS x FROM t",
        "limits",
    ),
    Attack("wide_result", "SELECT " + ", ".join(["1"] * 101), "limits"),
    Attack("deep_nesting", "SELECT " + "(" * 1500 + "1" + ")" * 1500, "ast"),
    Attack("long_expression_chain", "SELECT " + " + ".join(["1"] * 1200), "ast"),
    # Attempts to read masked columns through filters, joins, grouping, and ordering.
    Attack(
        "where_like", "SELECT FirstName FROM Customer WHERE Email LIKE 'ana%'", "ast", ("nulls",)
    ),
    Attack("order_by", "SELECT FirstName FROM Customer ORDER BY Phone", "ast", ("nulls",)),
    Attack("order_by_ordinal", "SELECT Email FROM Customer ORDER BY 1", "ast", ("nulls",)),
    Attack("group_by", "SELECT count(*) FROM Customer GROUP BY Email", "ast", ("nulls",)),
    Attack(
        "having",
        "SELECT Country FROM Customer GROUP BY Country HAVING max(Email) > 'a'",
        "ast",
        ("nulls",),
    ),
    Attack(
        "join_on",
        "SELECT c.FirstName FROM Customer c JOIN Employee e ON c.Email = e.Email",
        "ast",
        ("nulls",),
    ),
    Attack(
        "exists_subquery",
        "SELECT FirstName FROM Customer c "
        "WHERE EXISTS (SELECT 1 FROM Employee e WHERE e.Email = c.Email)",
        "ast",
        ("nulls",),
    ),
    Attack(
        "in_subquery",
        "SELECT FirstName FROM Customer "
        "WHERE CustomerId IN (SELECT CustomerId FROM Customer WHERE Phone IS NULL)",
        "ast",
        ("nulls",),
    ),
    Attack(
        "derived_alias_filter",
        "SELECT x FROM (SELECT Email AS x FROM Customer) WHERE x LIKE 'ana%'",
        "ast",
        ("nulls",),
    ),
    Attack(
        "cte_filter",
        "WITH c AS (SELECT Email AS e FROM Customer) SELECT 1 FROM c WHERE e = 'ana@example.com'",
        "ast",
        ("nulls",),
    ),
    Attack(
        "limit_subquery",
        "SELECT Name FROM Artist LIMIT (SELECT length(Email) FROM Customer LIMIT 1)",
        "ast",
        ("nulls",),
    ),
    Attack(
        "union_order",
        "SELECT Email FROM Customer UNION SELECT FirstName FROM Customer ORDER BY 1",
        "ast",
        ("nulls",),
    ),
    Attack(
        "natural_join_on_email",
        "SELECT c.FirstName FROM Customer c NATURAL JOIN Employee e",
        "ast",
        ("nulls",),
    ),
    Attack(
        "using_email",
        "SELECT c.FirstName FROM Customer c JOIN Employee e USING (Email)",
        "ast",
        ("nulls",),
    ),
    Attack(
        "correlated_subquery_filter",
        "SELECT c.FirstName FROM Customer c WHERE (SELECT count(*) FROM Invoice i "
        "WHERE i.CustomerId = c.CustomerId AND c.Email LIKE 'ana%') > 0",
        "ast",
        ("nulls",),
    ),
    Attack(
        "billing_address_filter",
        "SELECT InvoiceId FROM Invoice WHERE BillingAddress LIKE 'Rua%'",
        "ast",
        ("nulls",),
    ),
    Attack(
        "birth_date_filter",
        "SELECT FirstName FROM Employee WHERE BirthDate < '1980-01-01'",
        "ast",
        ("nulls",),
    ),
)


def _ids(attacks: tuple[Attack, ...]) -> list[str]:
    return [attack.id for attack in attacks]


def _with_backstop(backstop: Backstop) -> tuple[Attack, ...]:
    return tuple(attack for attack in ATTACKS if backstop in attack.backstops)


@pytest.fixture(autouse=True)
def _isolated_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run each attack in an empty directory, so a file-writing attack would be visible."""
    monkeypatch.chdir(tmp_path)


def test_attack_ids_are_unique() -> None:
    assert len(set(_ids(ATTACKS))) == len(ATTACKS)


@pytest.mark.parametrize("attack", ATTACKS, ids=_ids(ATTACKS))
def test_attack_is_blocked(
    attack: Attack, db_path: Path, tmp_path: Path, sensitive_values: tuple[str, ...]
) -> None:
    before = db_path.read_bytes()
    with pytest.raises(QueryRejectedError) as error:
        run_query(db_path, attack.sql, FAST)
    assert error.value.layer == attack.blocked_by
    message = error.value.reason
    assert all(value not in message for value in sensitive_values)
    assert db_path.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [db_path.name]


@pytest.mark.parametrize("attack", _with_backstop("driver"), ids=_ids(_with_backstop("driver")))
def test_driver_runs_a_single_statement(attack: Attack, db_path: Path) -> None:
    with guarded_connection(db_path, TABLES) as conn, pytest.raises(QueryFailedError) as error:
        execute(conn, attack.sql, FAST)
    assert "one statement" in str(error.value)


@pytest.mark.parametrize(
    "attack", _with_backstop("authorizer"), ids=_ids(_with_backstop("authorizer"))
)
def test_authorizer_blocks_without_the_ast_layer(
    attack: Attack, db_path: Path, tmp_path: Path
) -> None:
    before = db_path.read_bytes()
    with guarded_connection(db_path, TABLES) as conn, pytest.raises(QueryRejectedError) as error:
        execute(conn, attack.sql, FAST)
    assert error.value.layer == "authorizer"
    assert db_path.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [db_path.name]


@pytest.mark.parametrize(
    "attack", _with_backstop("read_only"), ids=_ids(_with_backstop("read_only"))
)
def test_read_only_blocks_without_ast_and_authorizer(attack: Attack, db_path: Path) -> None:
    before = db_path.read_bytes()
    with guarded_connection(db_path, TABLES) as conn:
        conn.set_authorizer(None)
        with pytest.raises(QueryRejectedError) as error:
            execute(conn, attack.sql, FAST)
    assert error.value.layer == "read_only"
    assert db_path.read_bytes() == before


@pytest.mark.parametrize("attack", _with_backstop("nulls"), ids=_ids(_with_backstop("nulls")))
def test_sensitive_values_never_leave_sqlite(
    attack: Attack, db_path: Path, sensitive_values: tuple[str, ...]
) -> None:
    with guarded_connection(db_path, TABLES) as conn:
        try:
            _, rows, _ = execute(conn, attack.sql, FAST)
        except QueryFailedError as error:
            # Some oracles fail on NULL (e.g., LIMIT NULL); failing leaks nothing either.
            text = str(error)
        else:
            text = repr(rows)
    assert all(value not in text for value in sensitive_values)
