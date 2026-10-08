---
name: novo-mcp
description: Cria um novo servidor MCP em servers/<nome>/ no padrão do repositório.
---

# Novo servidor MCP

Cria um servidor MCP com transporte stdio em `servers/<server-name>/`, como membro do workspace `uv`.

## Procedimento

1. **Nome e descrição.** Receba do usuário o nome em kebab-case (`<server-name>`, ex.: `sqlite-consulta`) e uma descrição de uma linha. Derive o pacote Python em snake_case (`<package_name>`, ex.: `sqlite_consulta`). Confirme que `servers/<server-name>/` ainda não existe.
2. **Design Doc.** Se o servidor envolve segurança ou dados, mais de um componente ou mais de um dia de trabalho, ele exige Design Doc (ADR-0005). Procure-o em `docs/design/`; se não existir, pare e crie-o (a partir de `docs/design/0000-template.md`) com o usuário antes de seguir.
3. **Arquivos.** Crie os arquivos abaixo, trocando `<server-name>`, `<package_name>` e `<one-line description>`:
   - `servers/<server-name>/pyproject.toml`
   - `servers/<server-name>/README.md`
   - `servers/<server-name>/src/<package_name>/__init__.py`
   - `servers/<server-name>/src/<package_name>/server.py`
   - `servers/<server-name>/tests/test_server.py`
4. **Workspace.** Na raiz, rode `uv add <server-name>`. Isso adiciona o servidor às `dependencies` da raiz e cria `<server-name> = { workspace = true }` em `[tool.uv.sources]`. Sem esse passo, `uv sync --all-groups` não instala o servidor e os testes dele não conseguem importá-lo.
5. **mypy.** No `pyproject.toml` da raiz, acrescente `"servers/<server-name>/src"` e `"servers/<server-name>/tests"` a `[tool.mypy] files`.
6. **Validação.** Na raiz do repositório, rode e só conclua com tudo passando:
   ```bash
   uv sync --all-groups
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy
   uv run pytest
   ```
   O `uv.lock` atualizado deve entrar no commit, junto com o `pyproject.toml` da raiz.
7. **Decisões.** Lembre o usuário de registrar em ADR (skill `novo-adr`) qualquer decisão técnica nova, por exemplo uma dependência adicional.

Regra do repositório (ADR-0004): servidor stdio nunca usa `print()` nem escreve no stdout; logs via `logging` para stderr.

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

Se a versão do `uv` instalada for outra, use a faixa de `uv_build` que `uv init --package` gerar.

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
