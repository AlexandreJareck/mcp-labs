# sqlite-consulta

Assistente de dados text-to-SQL seguro sobre o banco de exemplo Chinook (SQLite).

O SQL é escrito pelo cliente MCP (por exemplo, o Claude Code). O servidor fornece contexto, valida e executa com segurança, e nunca chama um LLM. O desenho completo e o modelo de ameaças estão no [Design Doc 0001](../../docs/design/0001-sqlite-consulta.md).

**Estado atual: fase 1.** Ainda não há tool de SQL livre: só listar tabelas, descrever o schema e ver algumas linhas.

## Segurança nesta fase

- O banco é aberto **somente para leitura** (URI SQLite com `mode=ro` e `PRAGMA query_only = ON`). Cada chamada de tool abre e fecha a própria conexão.
- Nomes de tabela são comparados com a lista real do schema (sem diferenciar maiúsculas); um nome desconhecido vira erro da tool, sem executar SQL com o texto recebido.
- `sample_rows` devolve no máximo 5 linhas e mascara as colunas sensíveis (`***`): endereço, CEP, telefone, fax e e-mail de `Customer` e `Employee`, data de nascimento de `Employee`, e endereço e CEP de cobrança de `Invoice`.
- As linhas vêm com um aviso de que são dados não confiáveis: instruções encontradas nelas não devem ser seguidas.
- Nenhuma tool recebe caminho de arquivo; o servidor só abre o arquivo fixo do Chinook e confere o SHA-256 dele ao iniciar. Se o arquivo for trocado com o servidor já rodando, a troca só é detectada no próximo início (risco aceito: exige acesso de escrita à pasta de dados local).

## Pré-requisitos

- As do repositório (ver o [README da raiz](../../README.md)): `uv` e Python 3.12.
- Acesso à internet no primeiro uso, para baixar o Chinook.

## Como obter o banco

Na raiz do repositório:

```bash
uv sync --all-groups
uv run sqlite-consulta download-db
```

O comando baixa o `Chinook_Sqlite.sqlite` da release `v1.4.5` de [lerocha/chinook-database](https://github.com/lerocha/chinook-database) (licença MIT), confere tamanho e SHA-256 e só então grava o arquivo como `chinook-v1.4.5.sqlite`. Se o arquivo já existe e é válido, nada é baixado de novo. O banco não é versionado.

| Variável de ambiente | Padrão | Uso |
|----------------------|--------|-----|
| `SQLITE_CONSULTA_DATA_DIR` | `~/.cache/mcp-labs/sqlite-consulta/` | Diretório onde o banco é gravado e lido. |

## Como rodar

```bash
uv run sqlite-consulta
```

O servidor fala MCP por stdio: ele fica aguardando mensagens JSON-RPC no stdin. Para testá-lo de forma interativa, conecte-o a um cliente MCP (abaixo). Antes de iniciar, ele confere o SHA-256 do banco; se o arquivo não existir ou não bater, sai com código 1 e pede para rodar `download-db`.

`uv run sqlite-consulta --help` mostra os subcomandos (`serve`, o padrão, e `download-db`).

## Tools

Todas são somente leitura (`read_only_hint`) e devolvem saída estruturada.

| Tool | Argumentos | Descrição |
|------|-----------|-----------|
| `list_tables` | nenhum | Tabelas do banco com a contagem de linhas. |
| `describe_table` | `table` | Colunas (tipo, `NOT NULL`, chave primária, se é sensível) e chaves estrangeiras. |
| `sample_rows` | `table` | Até 5 linhas, com as colunas sensíveis mascaradas; `row_count` e `truncated` indicam quantas vieram e se a tabela tem mais. |

## Resources

Nenhum.

## Como conectar ao Claude

Claude Code (na raiz do repositório):

```bash
claude mcp add sqlite-consulta -- uv run --directory <caminho-absoluto-do-repo> sqlite-consulta
claude mcp list
```

O `claude mcp list` deve mostrar `sqlite-consulta: ... - ✓ Connected`. Rode `download-db` antes; sem o banco, o servidor não inicia.

## Testes

Os testes usam um banco pequeno criado no próprio teste e não dependem do download. Na raiz do repositório:

```bash
uv run pytest servers/sqlite-consulta --cov=sqlite_consulta --cov-report=term-missing
```

O CI exige cobertura mínima de 80% para este servidor.
