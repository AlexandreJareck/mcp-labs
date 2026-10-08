from sqlite_consulta.server import ping


def test_ping_returns_pong() -> None:
    assert ping() == "pong"
