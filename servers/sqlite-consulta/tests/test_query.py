import json
from pathlib import Path

import pytest
from sqlglot import exp
from sqlite_consulta.database import MASK
from sqlite_consulta.query import (
    MAX_RESULT_CHARS,
    MAX_SQL_LENGTH,
    UNTRUSTED_DATA_NOTICE,
    Limits,
    QueryFailedError,
    QueryRejectedError,
    _Env,
    execute,
    guarded_connection,
    run_query,
)

TABLES = frozenset({"album", "artist", "customer", "employee", "invoice", 'odd"name'})


def _assert_no_sensitive_values(result: object, sensitive_values: tuple[str, ...]) -> None:
    text = repr(result)
    for value in sensitive_values:
        assert value not in text


@pytest.mark.parametrize(
    ("sql", "masked"),
    [
        ("SELECT Email FROM Customer", ["email"]),
        ("SELECT Email AS contact FROM Customer", ["contact"]),
        ("SELECT lower(Email) || '!' AS x, FirstName FROM Customer", ["x"]),
        ("SELECT length(Phone) AS n FROM Customer", ["n"]),
        ("SELECT count(Email) AS n FROM Customer", ["n"]),
        ("SELECT coalesce(Phone, 'none') AS p FROM Customer", ["p"]),
        ("SELECT CASE WHEN Email LIKE 'a%' THEN 1 ELSE 0 END AS flag FROM Customer", ["flag"]),
        ("SELECT row_number() OVER (ORDER BY Email) AS rn FROM Customer", ["rn"]),
        ("SELECT * FROM Customer", ["phone", "email"]),
        ("SELECT c.* FROM Customer AS c", ["phone", "email"]),
        ("SELECT x FROM (SELECT Email AS x FROM Customer)", ["x"]),
        ("WITH a AS (SELECT Email AS e FROM Customer) SELECT e FROM a", ["e"]),
        ("WITH a(e) AS (SELECT Email FROM Customer) SELECT upper(e) AS u FROM a", ["u"]),
        ("SELECT FirstName FROM Customer UNION ALL SELECT Email FROM Employee", ["firstname"]),
        ("SELECT (SELECT max(Email) FROM Customer) AS m", ["m"]),
        ("SELECT BirthDate FROM Employee", ["birthdate"]),
        ("SELECT BillingAddress, BillingCountry FROM Invoice", ["billingaddress"]),
        (
            "WITH RECURSIVE r(v, n) AS (SELECT Email, 1 FROM Customer "
            "UNION ALL SELECT v, n + 1 FROM r WHERE n < 2) SELECT v, n FROM r",
            ["v"],
        ),
    ],
)
def test_sensitive_output_is_masked(
    db_path: Path, sensitive_values: tuple[str, ...], sql: str, masked: list[str]
) -> None:
    result = run_query(db_path, sql)
    assert result["masked_columns"] == masked
    for row in result["rows"]:
        for name, value in zip(result["columns"], row, strict=True):
            if name in masked:
                assert value == MASK
    _assert_no_sensitive_values(result, sensitive_values)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT Name FROM Artist ORDER BY ArtistId DESC LIMIT 2 OFFSET 1",
            [["Artist 7"], ["Artist 6"]],
        ),
        (
            "SELECT c.Country, sum(i.Total) AS total FROM Customer AS c "
            "JOIN Invoice AS i ON i.CustomerId = c.CustomerId GROUP BY c.Country ORDER BY total",
            [["Brazil", 15]],
        ),
        (
            "SELECT e.FirstName, m.FirstName AS manager FROM Employee AS e "
            "LEFT JOIN Employee AS m ON e.ReportsTo = m.EmployeeId ORDER BY 1",
            [["Boss", None], ["Clerk", "Boss"]],
        ),
        (
            "SELECT FirstName FROM Customer WHERE CustomerId IN "
            "(SELECT CustomerId FROM Invoice WHERE Total > 5)",
            [["Ana"]],
        ),
        (
            "SELECT Name FROM Artist UNION SELECT Title FROM Album ORDER BY Name LIMIT 1",
            [["Artist 1"]],
        ),
        ("SELECT FirstName AS Email FROM Customer ORDER BY Email", [["Ana"], ["Bruno"]]),
        ("SELECT 1 + 1 AS two", [[2]]),
        (
            "SELECT c.FirstName, (SELECT sum(i.Total) FROM Invoice AS i "
            "WHERE i.CustomerId = c.CustomerId) AS total FROM Customer AS c ORDER BY 1",
            [["Ana", 15], ["Bruno", None]],
        ),
        ("SELECT DISTINCT BillingCountry FROM Invoice", [["Brazil"]]),
        ("SELECT a.Name FROM Artist AS a NATURAL JOIN Album LIMIT 1", [["Artist 1"]]),
        ('SELECT typeof(Payload) AS t FROM "Odd""Name"', [["blob"]]),
    ],
)
def test_allowed_queries_return_data(db_path: Path, sql: str, expected: list[list[object]]) -> None:
    result = run_query(db_path, sql)
    assert result["rows"] == expected
    assert result["masked_columns"] == []
    assert result["notice"] == UNTRUSTED_DATA_NOTICE


def test_result_envelope(db_path: Path) -> None:
    result = run_query(db_path, "SELECT ArtistId, Name FROM Artist WHERE ArtistId = 1")
    assert result["columns"] == ["artistid", "name"]
    assert result["rows"] == [[1, "Artist 1"]]
    assert result["row_count"] == 1
    assert result["truncated"] is False
    assert result["executed_sql"].startswith('SELECT "artist"."artistid"')


def test_row_limit_truncates(db_path: Path) -> None:
    result = run_query(
        db_path, "SELECT a.ArtistId FROM Artist AS a, Artist AS b", Limits(max_rows=10)
    )
    assert result["row_count"] == 10
    assert result["truncated"] is True


def test_values_above_the_size_limit_are_rejected(db_path: Path) -> None:
    sql = (
        "WITH RECURSIVE r(s) AS (SELECT 'x' UNION ALL SELECT s || s FROM r "
        "WHERE length(s) < 4096) SELECT max(s) AS s FROM r"
    )
    with pytest.raises(QueryRejectedError, match="size limit") as error:
        run_query(db_path, sql)
    assert error.value.layer == "limits"


def test_whole_result_size_is_capped(db_path: Path) -> None:
    sql = (
        "WITH RECURSIVE r(s) AS (SELECT 'x' UNION ALL SELECT s || s FROM r "
        "WHERE length(s) < 1024) SELECT max(r.s) AS s, a.ArtistId FROM r, Artist AS a, "
        "Artist AS b, Artist AS c GROUP BY a.ArtistId, b.ArtistId, c.ArtistId"
    )
    result = run_query(db_path, sql, Limits(max_rows=1000))
    assert result["truncated"] is True
    assert 0 < result["row_count"] < 512
    assert len(json.dumps(result["rows"])) <= MAX_RESULT_CHARS


def test_blob_cells_are_described(db_path: Path) -> None:
    result = run_query(db_path, 'SELECT Payload FROM "Odd""Name"')
    assert result["rows"] == [["<blob: 2 bytes>"]]


def test_prompt_injection_comes_back_as_data(injection_db_path: Path, injection_text: str) -> None:
    before = injection_db_path.read_bytes()
    result = run_query(injection_db_path, "SELECT Name FROM Artist")
    assert result["rows"] == [[injection_text]]
    assert result["notice"] == UNTRUSTED_DATA_NOTICE
    # Even if a model obeyed the text, the follow-up write is rejected.
    with pytest.raises(QueryRejectedError):
        run_query(injection_db_path, "DROP TABLE Customer")
    assert injection_db_path.read_bytes() == before


def test_authorizer_hides_sensitive_values_even_without_the_ast_layer(
    db_path: Path, sensitive_values: tuple[str, ...]
) -> None:
    with guarded_connection(db_path, TABLES) as conn:
        rows = conn.execute("SELECT Email, Phone, FirstName FROM Customer").fetchall()
        oracle = conn.execute("SELECT FirstName FROM Customer WHERE Email LIKE 'ana%'").fetchall()
    assert rows == [(None, None, "Ana"), (None, None, "Bruno")]
    assert oracle == []
    _assert_no_sensitive_values(rows, sensitive_values)


def test_too_long_sql_is_rejected(db_path: Path) -> None:
    with pytest.raises(QueryRejectedError) as error:
        run_query(db_path, "SELECT 1" + " " * MAX_SQL_LENGTH)
    assert error.value.layer == "ast"


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "   ",
        "SELEC 1",
        "SELECT (",
        "SELECT 1 UNION SELECT 1, 2",
        "SELECT *",
        "VALUES (1, 2)",
        "SELECT * FROM (VALUES (1, 2))",
        "SELECT * FROM generate_series(1, 3)",
        "(SELECT Name FROM Artist)",
    ],
)
def test_invalid_sql_is_rejected(db_path: Path, sql: str) -> None:
    with pytest.raises(QueryRejectedError) as error:
        run_query(db_path, sql)
    assert error.value.layer == "ast"


@pytest.mark.parametrize(
    "sql", ["SELECT ntile(0) OVER () AS x", "(SELECT 1 AS x) UNION (SELECT 2 AS x)"]
)
def test_runtime_errors_are_reported(db_path: Path, sql: str) -> None:
    with pytest.raises(QueryFailedError, match="query failed"):
        run_query(db_path, sql)


def test_unresolvable_columns_are_treated_as_sensitive() -> None:
    env = _Env(tables={})
    assert env.column_tainted(exp.column("email", table="ghost")) is True


def test_read_only_layer_blocks_writes_without_the_authorizer(db_path: Path) -> None:
    with guarded_connection(db_path, TABLES) as conn:
        conn.set_authorizer(None)
        with pytest.raises(QueryRejectedError) as error:
            execute(conn, "DELETE FROM Artist", Limits())
    assert error.value.layer == "read_only"
