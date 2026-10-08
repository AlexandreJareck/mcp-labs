---
name: new-mcp-server
description: Creates a new MCP server in servers/<nome>/ following the repository's standard.
---

# New MCP server

Creates an MCP server with stdio transport in `servers/<server-name>/`, as a member of the `uv` workspace.

## Procedure

1. **Name and description.** Get from the user the name in kebab-case (`<server-name>`, e.g., `sqlite-consulta`) and a one-line description. Derive the Python package name in snake_case (`<package_name>`, e.g., `sqlite_consulta`). Confirm that `servers/<server-name>/` does not exist yet.
2. **Design Doc.** If the server involves security or data, more than one component, or more than one day of work, it requires a Design Doc (ADR-0005). Look for it in `docs/design/`; if it does not exist, stop and create it (from `docs/design/0000-template.md`) with the user before continuing.
3. **Files.** Create the files below, replacing `<server-name>`, `<package_name>`, and `<one-line description>`:
   - `servers/<server-name>/pyproject.toml`
   - `servers/<server-name>/README.md`
   - `servers/<server-name>/src/<package_name>/__init__.py`
   - `servers/<server-name>/src/<package_name>/server.py`
   - `servers/<server-name>/tests/test_server.py`
4. **Workspace.** At the root, run `uv add <server-name>`. This adds the server to the root `dependencies` and creates `<server-name> = { workspace = true }` in `[tool.uv.sources]`. Without this step, `uv sync --all-groups` does not install the server and its tests cannot import it.
5. **mypy.** In the root `pyproject.toml`, add `"servers/<server-name>/src"` and `"servers/<server-name>/tests"` to `[tool.mypy] files`.
6. **Validation.** At the repository root, run the following and only finish when everything passes:
   ```bash
   uv sync --all-groups
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   uv run pytest
   ```
   The updated `uv.lock` must go into the commit, together with the root `pyproject.toml`.
7. **Decisions.** Remind the user to record any new technical decision in an ADR (skill `new-adr`), for example an additional dependency.

Repository rules:

- A stdio server never uses `print()` or writes to stdout; logs go via `logging` to stderr (ADR-0004).
- Code, docstrings, and identifiers in English; the server's `README.md` in Portuguese (ADR-0003). Use the README template below without translating it.

## Templates

### `pyproject.toml`

```toml
[project]
name = "<server-name>"
version = "0.1.0"
description = "<one-line description>"
readme = "README.md"
requires-python = ">=3.12"
dependencies = ["mcp"]

[project.scripts]
<server-name> = "<package_name>.server:main"

[build-system]
requires = ["uv_build>=0.11.8,<0.12.0"]
build-backend = "uv_build"
```

If the installed `uv` version is different, use the `uv_build` range that `uv init --package` generates.

### `src/<package_name>/__init__.py`

```python
"""<one-line description>"""
```

### `src/<package_name>/server.py`

```python
"""MCP server entrypoint."""

import logging
import sys

from mcp.server import MCPServer

logger = logging.getLogger(__name__)

mcp = MCPServer("<server-name>")


@mcp.tool()
def ping() -> str:
    """Return "pong" to confirm the server is reachable."""
    return "pong"


def main() -> None:
    """Start the server over stdio."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    logger.info("Starting <server-name> over stdio")
    mcp.run()
```

### `tests/test_server.py`

```python
from <package_name>.server import ping


def test_ping_returns_pong() -> None:
    assert ping() == "pong"
```

### `README.md`

````markdown
# <server-name>

<one-line description>

## Como rodar

Na raiz do repositório:

```bash
uv sync --all-groups
uv run <server-name>
```

O servidor fala MCP por stdio: ele fica aguardando mensagens JSON-RPC no stdin. Para testá-lo de forma interativa, conecte-o a um cliente MCP (abaixo).

## Tools

| Tool | Descrição |
|------|-----------|
| `ping` | Retorna `pong` para confirmar que o servidor responde. |

## Resources

Nenhum.

## Como conectar ao Claude

Claude Code (na raiz do repositório):

```bash
claude mcp add <server-name> -- uv run --directory <caminho-absoluto-do-repo> <server-name>
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "<server-name>": {
      "command": "uv",
      "args": ["run", "--directory", "<caminho-absoluto-do-repo>", "<server-name>"]
    }
  }
}
```
````
