import hashlib
import io
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlite_consulta import chinook
from sqlite_consulta.chinook import (
    CHINOOK,
    DatabaseIntegrityError,
    DatabaseNotFoundError,
    DatabaseRelease,
    database_path,
    download_database,
    verify_database,
)

PAYLOAD = b"fake database content " * 100


def _release(payload: bytes = PAYLOAD, url: str = "https://example.invalid/db") -> DatabaseRelease:
    return DatabaseRelease(
        url=url,
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        filename="test.sqlite",
    )


@dataclass
class FakeServer:
    """Stands in for the network: records requested URLs and serves `body`."""

    body: bytes = PAYLOAD
    requested: list[str] = field(default_factory=list)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    fake = FakeServer()

    def fake_urlopen(url: str, timeout: float) -> io.BytesIO:
        fake.requested.append(url)
        return io.BytesIO(fake.body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return fake


def test_pinned_release_matches_design_doc() -> None:
    assert CHINOOK.url.startswith("https://github.com/lerocha/chinook-database/releases/")
    assert "/v1.4.5/" in CHINOOK.url
    assert CHINOOK.sha256 == "bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a"
    assert CHINOOK.size == 1_067_008


def test_database_path_uses_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    assert database_path() == tmp_path.resolve() / CHINOOK.filename


def test_database_path_defaults_to_user_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(chinook.DATA_DIR_ENV, raising=False)
    assert database_path() == chinook.DEFAULT_DATA_DIR / CHINOOK.filename


def test_verify_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DatabaseNotFoundError, match="download-db"):
        verify_database(tmp_path / "missing.sqlite", _release())


def test_verify_wrong_size(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    path.write_bytes(PAYLOAD + b"x")
    with pytest.raises(DatabaseIntegrityError, match="size"):
        verify_database(path, _release())


def test_verify_wrong_hash_same_size(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    path.write_bytes(secrets.token_bytes(len(PAYLOAD)))
    with pytest.raises(DatabaseIntegrityError, match="SHA-256"):
        verify_database(path, _release())


def test_verify_accepts_matching_file(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    path.write_bytes(PAYLOAD)
    verify_database(path, _release())


def test_download_writes_verified_file(served: FakeServer, tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "db.sqlite"
    assert download_database(destination, _release()) == destination
    assert destination.read_bytes() == PAYLOAD
    assert served.requested == ["https://example.invalid/db"]
    assert list(destination.parent.iterdir()) == [destination]


def test_download_skips_when_file_is_valid(served: FakeServer, tmp_path: Path) -> None:
    destination = tmp_path / "db.sqlite"
    destination.write_bytes(PAYLOAD)
    download_database(destination, _release())
    assert served.requested == []


def test_download_with_wrong_hash_leaves_nothing(served: FakeServer, tmp_path: Path) -> None:
    served.body = secrets.token_bytes(len(PAYLOAD))
    destination = tmp_path / "db.sqlite"
    with pytest.raises(DatabaseIntegrityError):
        download_database(destination, _release())
    assert list(tmp_path.iterdir()) == []


def test_download_larger_than_expected_is_aborted(served: FakeServer, tmp_path: Path) -> None:
    served.body = PAYLOAD * 200
    destination = tmp_path / "db.sqlite"
    with pytest.raises(DatabaseIntegrityError, match="larger"):
        download_database(destination, _release())
    assert list(tmp_path.iterdir()) == []


def test_download_replaces_corrupted_file(served: FakeServer, tmp_path: Path) -> None:
    destination = tmp_path / "db.sqlite"
    destination.write_bytes(b"corrupted")
    download_database(destination, _release())
    assert destination.read_bytes() == PAYLOAD


@pytest.mark.parametrize("url", ["http://example.invalid/db", "file:///etc/passwd"])
def test_download_refuses_non_https(served: FakeServer, tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        download_database(tmp_path / "db.sqlite", _release(url=url))
    assert served.requested == []
