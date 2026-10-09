"""Structured audit log of queries, written to stderr through `logging` (ADR-0004).

Each query produces one JSON line. The SQL is normalized with every literal
replaced by ``?``, because literals can hold personal data typed by the user.
Result values are never logged, and neither is anything that comes from the
database.
"""

import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

audit_logger = logging.getLogger("sqlite_consulta.audit")

type Decision = Literal["allowed", "rejected", "confirmed", "declined", "failed"]

UNPARSEABLE = "<unparseable>"
MAX_LOGGED_SQL = 2_000


def _mask_values(node: exp.Expr) -> exp.Expr:
    # Literals of every kind become placeholders. Quoted identifiers are masked too:
    # SQLite reads an unknown "double-quoted" name as a string literal.
    if isinstance(node, exp.Literal | exp.HexString | exp.Boolean):
        return exp.Placeholder()
    if isinstance(node, exp.Identifier) and node.quoted:
        return exp.Identifier(this="?", quoted=False)
    return node


def normalize_sql(sql: str) -> str:
    """Return the SQL with every literal replaced by a placeholder.

    Args:
        sql: SQL sent by the client.

    Literals (strings, numbers, hex blobs, booleans) and quoted identifiers
    become ``?``.

    Returns:
        The normalized SQL (truncated), or a marker when it cannot be parsed.
        Text that cannot be parsed is never logged, since it may hold literals.
    """
    try:
        trees = sqlglot.parse(sql, read="sqlite")
    except (SqlglotError, RecursionError):
        return UNPARSEABLE
    statements: list[str] = []
    for tree in trees:
        if tree is None:
            continue
        normalized = tree.transform(_mask_values)
        statements.append(normalized.sql(dialect="sqlite"))
    text = "; ".join(statements) or UNPARSEABLE
    return text if len(text) <= MAX_LOGGED_SQL else text[:MAX_LOGGED_SQL] + "..."


@dataclass
class AuditRecord:
    """Mutable outcome of one audited query.

    Attributes:
        decision: What happened to the query.
        reason: Short, data-free explanation (a layer name or a fixed message).
        row_count: Number of rows returned, when the query ran.
        estimated_cost: Estimated rows examined, when known.
    """

    decision: Decision = "failed"
    reason: str = ""
    row_count: int | None = None
    estimated_cost: int | None = None


def configure_audit_logging() -> None:
    """Send audit lines to stderr as bare JSON, without the root logger's prefix."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.handlers = [handler]
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False


def _emit(entry: dict[str, object]) -> None:
    entry = {"timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"), **entry}
    audit_logger.info(json.dumps(entry, ensure_ascii=True, separators=(",", ":")))


_DEDUPE_SECONDS = 2.0
_last_request: tuple[str, float] | None = None


def log_confirmation_requested(sql: str, estimated_cost: int) -> None:
    """Record that the user was asked to confirm an expensive query.

    The protocol calls the resolver twice for one query (ask, then re-run with
    the answer), so the same request within a short window is logged once.

    Args:
        sql: SQL sent by the client.
        estimated_cost: Estimated number of rows examined.
    """
    global _last_request
    now = time.monotonic()
    if _last_request is not None:
        last_sql, last_time = _last_request
        if last_sql == sql and now - last_time < _DEDUPE_SECONDS:
            return
    _last_request = (sql, now)
    _emit(
        {
            "event": "confirmation_requested",
            "tool": "run_query",
            "sql_normalized": normalize_sql(sql),
            "estimated_cost": estimated_cost,
        }
    )


def log_query(
    tool: str,
    sql: str,
    decision: Decision,
    reason: str,
    estimated_cost: int | None = None,
) -> None:
    """Write one audit line for a query that never reached the tool body.

    Args:
        tool: Name of the tool.
        sql: SQL sent by the client.
        decision: What happened to the query.
        reason: Short, data-free explanation.
        estimated_cost: Estimated number of rows examined, when known.
    """
    _emit(
        {
            "event": "query",
            "tool": tool,
            "sql_normalized": normalize_sql(sql),
            "decision": decision,
            "reason": reason,
            "duration_ms": 0.0,
            "row_count": None,
            "estimated_cost": estimated_cost,
        }
    )


@contextmanager
def audited(tool: str, sql: str) -> Iterator[AuditRecord]:
    """Write one audit line when the audited block ends, even on errors.

    Args:
        tool: Name of the tool being audited.
        sql: SQL sent by the client.

    Yields:
        The record to fill in with the decision and the outcome.
    """
    record = AuditRecord()
    started = time.perf_counter()
    try:
        yield record
    except BaseException:
        if record.decision == "failed" and not record.reason:
            record.reason = "unexpected error"
        raise
    finally:
        _emit(
            {
                "event": "query",
                "tool": tool,
                "sql_normalized": normalize_sql(sql),
                "decision": record.decision,
                "reason": record.reason,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "row_count": record.row_count,
                "estimated_cost": record.estimated_cost,
            }
        )
