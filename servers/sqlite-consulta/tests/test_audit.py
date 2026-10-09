import json
import logging
import time

import pytest
from sqlite_consulta import audit
from sqlite_consulta.audit import UNPARSEABLE, audited, normalize_sql

LOGGER = "sqlite_consulta.audit"


def _lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == LOGGER]


def test_literals_are_replaced_by_placeholders() -> None:
    sql = "SELECT FirstName FROM Customer WHERE Country = 'Brazil' AND CustomerId > 10"
    normalized = normalize_sql(sql)
    assert "Brazil" not in normalized
    assert "10" not in normalized
    assert normalized.count("?") == 2


def test_normalization_covers_literals_in_every_clause() -> None:
    sql = (
        "SELECT 'secret-a' AS a FROM Artist WHERE Name IN ('secret-b', 'secret-c') "
        "ORDER BY length('secret-d') LIMIT 5"
    )
    normalized = normalize_sql(sql)
    assert "secret" not in normalized
    assert "5" not in normalized


@pytest.mark.parametrize(
    ("sql", "secret"),
    [
        ("SELECT Name FROM Artist WHERE Payload = x'deadbeef'", "deadbeef"),
        ('SELECT Name FROM Artist WHERE Name = "secret-name"', "secret-name"),
        ("SELECT Name FROM Artist WHERE flag = true", "true"),
    ],
)
def test_other_literal_forms_are_masked(sql: str, secret: str) -> None:
    assert secret not in normalize_sql(sql).lower()


def test_unparseable_sql_is_never_logged() -> None:
    assert normalize_sql("SELECT 'abc@example.com' FROM (") == UNPARSEABLE


def test_deeply_nested_sql_is_never_logged() -> None:
    assert normalize_sql("SELECT " + "(" * 5000 + "'x@y.z'" + ")" * 5000) == UNPARSEABLE


def test_logged_sql_is_truncated() -> None:
    sql = "SELECT " + ", ".join(f"c{i}" for i in range(2000)) + " FROM t"  # noqa: S608
    assert len(normalize_sql(sql)) <= audit.MAX_LOGGED_SQL + 3


def test_one_json_line_per_query(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    with audited("run_query", "SELECT 1 FROM Artist WHERE Name = 'x@y.z'") as record:
        record.decision = "allowed"
        record.row_count = 3
        record.estimated_cost = 10
    (line,) = _lines(caplog)
    assert line["tool"] == "run_query"
    assert line["event"] == "query"
    assert line["decision"] == "allowed"
    assert line["row_count"] == 3
    assert line["estimated_cost"] == 10
    assert isinstance(line["duration_ms"], float)
    assert "x@y.z" not in json.dumps(line)
    assert str(line["timestamp"]).endswith("+00:00")


def test_errors_are_logged_and_reraised(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    with pytest.raises(RuntimeError), audited("run_query", "SELECT 1"):
        raise RuntimeError("boom")
    (line,) = _lines(caplog)
    assert line["decision"] == "failed"
    assert line["reason"] == "unexpected error"


def test_duration_is_measured(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    with audited("run_query", "SELECT 1") as record:
        time.sleep(0.02)
        record.decision = "allowed"
    (line,) = _lines(caplog)
    assert float(str(line["duration_ms"])) >= 15


def test_log_query_line(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    audit.log_query("run_query", "SELECT 'a' FROM Artist", "declined", "client cannot confirm", 42)
    (line,) = _lines(caplog)
    assert line["decision"] == "declined"
    assert line["estimated_cost"] == 42
    assert "'a'" not in str(line["sql_normalized"])


def test_confirmation_requests_are_deduplicated(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    monkeypatch.setattr(audit, "_last_request", None)
    audit.log_confirmation_requested("SELECT 1 FROM Artist", 5)
    audit.log_confirmation_requested("SELECT 1 FROM Artist", 5)
    audit.log_confirmation_requested("SELECT 2 FROM Artist", 5)
    lines = _lines(caplog)
    assert [line["event"] for line in lines] == ["confirmation_requested"] * 2


def test_configure_writes_bare_json_to_stderr(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    logger = logging.getLogger(LOGGER)
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "propagate", True)
    audit.configure_audit_logging()
    with audited("run_query", "SELECT 1") as record:
        record.decision = "allowed"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err.strip().splitlines()[-1])["decision"] == "allowed"
    assert logger.propagate is False
