"""Obtain and verify the Chinook sample database (ADR-0009)."""

import hashlib
import logging
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

logger = logging.getLogger(__name__)

DATA_DIR_ENV = "SQLITE_CONSULTA_DATA_DIR"
DEFAULT_DATA_DIR = Path.home() / ".cache" / "mcp-labs" / "sqlite-consulta"
DOWNLOAD_TIMEOUT_SECONDS = 60
_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class DatabaseRelease:
    """A pinned release of a database file.

    Attributes:
        url: HTTPS URL of the release asset.
        sha256: Expected SHA-256 of the file, in lowercase hex.
        size: Expected size of the file, in bytes.
        filename: Local file name used inside the data directory.
    """

    url: str
    sha256: str
    size: int
    filename: str


CHINOOK = DatabaseRelease(
    url=(
        "https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_Sqlite.sqlite"
    ),
    sha256="bdf635be69850bd3be09c9a2dbeef7ddfb80036bd3ef3381383cd03b61e4a61a",
    size=1_067_008,
    filename="chinook-v1.4.5.sqlite",
)


class DatabaseError(Exception):
    """Base error for problems obtaining or verifying the database."""


class DatabaseNotFoundError(DatabaseError):
    """The database file does not exist yet."""


class DatabaseIntegrityError(DatabaseError):
    """The database file does not match the pinned size or hash."""


def data_dir() -> Path:
    """Return the directory that holds the database.

    Returns:
        The directory from `SQLITE_CONSULTA_DATA_DIR`, or the default cache directory.
    """
    configured = os.environ.get(DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_DATA_DIR


def database_path(release: DatabaseRelease = CHINOOK) -> Path:
    """Return the fixed path of the database file inside the data directory.

    Args:
        release: The pinned release whose file name is used.

    Returns:
        Absolute path of the database file.
    """
    return data_dir() / release.filename


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_database(path: Path, release: DatabaseRelease = CHINOOK) -> None:
    """Check that the database file exists and matches the pinned release.

    Args:
        path: Path of the database file.
        release: The pinned release to compare against.

    Raises:
        DatabaseNotFoundError: If the file does not exist.
        DatabaseIntegrityError: If the size or the SHA-256 does not match.
    """
    if not path.is_file():
        raise DatabaseNotFoundError(
            f"Database not found at {path}. Run 'uv run sqlite-consulta download-db' first."
        )
    if path.stat().st_size != release.size:
        raise DatabaseIntegrityError(f"Database at {path} has an unexpected size.")
    if _sha256_of(path) != release.sha256:
        raise DatabaseIntegrityError(f"Database at {path} does not match the pinned SHA-256.")


def _copy_limited(source: BinaryIO, target: BinaryIO, max_size: int) -> None:
    written = 0
    for chunk in iter(lambda: source.read(_CHUNK_SIZE), b""):
        written += len(chunk)
        if written > max_size:
            raise DatabaseIntegrityError("Downloaded file is larger than expected.")
        target.write(chunk)


def download_database(destination: Path, release: DatabaseRelease = CHINOOK) -> Path:
    """Download the pinned release and move it into place only after verifying it.

    The file is written to a temporary file in the destination directory, checked
    against the pinned size and SHA-256, and then renamed atomically. An existing
    valid file is kept as is.

    Args:
        destination: Final path of the database file.
        release: The pinned release to download.

    Returns:
        The destination path.

    Raises:
        DatabaseIntegrityError: If the downloaded file does not match the release.
        ValueError: If the release URL is not HTTPS.
    """
    if not release.url.startswith("https://"):
        raise ValueError("Only HTTPS downloads are allowed.")
    try:
        verify_database(destination, release)
    except DatabaseError:
        pass
    else:
        logger.info("Database already present and verified at %s", destination)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s", release.url)
    fd, temp_name = tempfile.mkstemp(dir=destination.parent, suffix=".part")
    temp_path = Path(temp_name)
    try:
        # The scheme is checked above, so urlopen cannot read local files.
        with (
            os.fdopen(fd, "wb") as target,
            urllib.request.urlopen(release.url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,  # noqa: S310
        ):
            _copy_limited(response, target, release.size)
        verify_database(temp_path, release)
        temp_path.replace(destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    logger.info("Database downloaded and verified at %s", destination)
    return destination
