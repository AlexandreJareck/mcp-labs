"""Turn the repository conventions into automated checks."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVERS_DIR = ROOT / "servers"

REQUIRED_FILES: tuple[str, ...] = (
    ".claude/agents/revisor.md",
    ".claude/skills/novo-adr/SKILL.md",
    ".claude/skills/novo-mcp/SKILL.md",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    "docs/adr/0000-template.md",
    "docs/design/0000-template.md",
    "docs/estudos/README.md",
    "tests/test_repository_layout.py",
    ".gitignore",
    ".pre-commit-config.yaml",
    ".python-version",
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
)

SERVER_REQUIRED_ENTRIES: tuple[str, ...] = ("README.md", "pyproject.toml", "src", "tests")


def _server_dirs() -> list[Path]:
    return sorted(path for path in SERVERS_DIR.iterdir() if path.is_dir())


def _mypy_files() -> list[str]:
    with (ROOT / "pyproject.toml").open("rb") as file:
        config = tomllib.load(file)
    files: list[str] = config["tool"]["mypy"]["files"]
    return files


@pytest.mark.parametrize("relative_path", REQUIRED_FILES)
def test_required_file_exists(relative_path: str) -> None:
    assert (ROOT / relative_path).is_file(), f"missing required file: {relative_path}"


def test_initial_adrs_exist() -> None:
    for number in range(1, 6):
        matches = list((ROOT / "docs" / "adr").glob(f"{number:04d}-*.md"))
        assert len(matches) == 1, f"expected exactly one ADR numbered {number:04d}"


def test_servers_have_required_entries() -> None:
    for server in _server_dirs():
        for entry in SERVER_REQUIRED_ENTRIES:
            assert (server / entry).exists(), f"{server.name} is missing {entry}"


def test_servers_are_type_checked() -> None:
    mypy_files = _mypy_files()
    for server in _server_dirs():
        for subdir in ("src", "tests"):
            expected = f"servers/{server.name}/{subdir}"
            assert expected in mypy_files, f"{expected} is missing from [tool.mypy] files"
