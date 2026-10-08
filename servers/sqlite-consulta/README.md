# sqlite-consulta

Assistente de dados text-to-SQL seguro sobre o banco de exemplo Chinook (SQLite).

## Como rodar

Na raiz do repositório:

```bash
uv sync --all-groups
uv run sqlite-consulta
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
claude mcp add sqlite-consulta -- uv run --directory <caminho-absoluto-do-repo> sqlite-consulta
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sqlite-consulta": {
      "command": "uv",
      "args": ["run", "--directory", "<caminho-absoluto-do-repo>", "sqlite-consulta"]
    }
  }
}
```
