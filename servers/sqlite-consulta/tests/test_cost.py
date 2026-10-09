from pathlib import Path

import pytest
from sqlite_consulta.query import prepare_query, run_prepared

# Test database sizes: Artist 8, Album 1, Customer 2, Employee 2, Invoice 2.
# Each plan node adds about 1 to the estimate, hence the small upper margins.


@pytest.mark.parametrize(
    ("sql", "low", "high"),
    [
        ("SELECT Name FROM Artist WHERE ArtistId = 1", 1, 2),
        ("SELECT Name FROM Artist", 8, 12),
        ("SELECT count(*) FROM Artist a, Artist b", 64, 70),
        ("SELECT count(*) FROM Artist a, Artist b, Artist c", 512, 520),
        ("SELECT a.Name FROM Album b JOIN Artist a ON a.ArtistId = b.ArtistId", 1, 3),
        ("SELECT Name FROM Artist UNION SELECT FirstName FROM Customer", 10, 16),
        (
            "SELECT a.Name, (SELECT count(*) FROM Artist b WHERE b.Name > a.Name) AS n "
            "FROM Artist a",
            72,
            90,
        ),
        ("SELECT count(*) FROM (SELECT DISTINCT Name FROM Artist) x, Artist y", 64, 80),
    ],
)
def test_cost_estimate(db_path: Path, sql: str, low: int, high: int) -> None:
    cost = prepare_query(db_path, sql).estimated_cost
    assert low <= cost <= high


def test_prepared_query_runs_as_validated(db_path: Path) -> None:
    prepared = prepare_query(db_path, "SELECT count(*) AS n FROM Artist a, Artist b")
    assert run_prepared(db_path, prepared)["rows"] == [[64]]
