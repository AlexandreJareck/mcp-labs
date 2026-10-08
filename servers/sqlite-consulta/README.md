# sqlite-consulta

Assistente de dados text-to-SQL seguro sobre o banco de exemplo Chinook (SQLite).

O SQL é escrito pelo cliente MCP (por exemplo, o Claude Code). O servidor fornece contexto, valida e executa com segurança, e nunca chama um LLM. O desenho completo e o modelo de ameaças estão no [Design Doc 0001](../../docs/design/0001-sqlite-consulta.md).

**Estado atual: fase 2.** Além de listar tabelas, descrever o schema e ver algumas linhas, o servidor executa SQL livre de leitura (`run_query`), protegido em camadas.

## Segurança

- O banco é aberto **somente para leitura** (URI SQLite com `mode=ro` e `PRAGMA query_only = ON`). Cada chamada de tool abre e fecha a própria conexão.
- Nomes de tabela são comparados com a lista real do schema (sem diferenciar maiúsculas); um nome desconhecido vira erro da tool, sem executar SQL com o texto recebido.
- `sample_rows` devolve no máximo 5 linhas e mascara as colunas sensíveis (`***`): endereço, CEP, telefone, fax e e-mail de `Customer` e `Employee`, data de nascimento de `Employee`, e endereço e CEP de cobrança de `Invoice`.
- As linhas vêm com um aviso de que são dados não confiáveis: instruções encontradas nelas não devem ser seguidas.
- `run_query` passa por cinco camadas (detalhes no Design Doc):
  1. **AST** (`sqlglot`): uma única consulta `SELECT` sobre tabelas conhecidas; escrita, DDL, `PRAGMA`, `ATTACH`, transações e funções fora da allowlist são rejeitadas, mesmo escondidas em CTE ou subconsulta. Colunas sensíveis não podem aparecer em `WHERE`, `JOIN`, `GROUP BY`, `HAVING`, `ORDER BY` nem `LIMIT`.
  2. **Somente leitura**: a mesma conexão `mode=ro` + `query_only`, sem bancos anexados.
  3. **Authorizer do SQLite**: nega tudo que não for leitura de tabela conhecida ou função permitida, e devolve `NULL` no lugar de colunas sensíveis.
  4. **Limites**: 2 segundos por consulta, 200 linhas, 100 colunas, 2.000 bytes por valor, padrões de `LIKE`/`GLOB` de até 50 caracteres, cerca de 200.000 caracteres na resposta inteira e SQL de até 5.000 caracteres. O limite por valor existe porque funções como `like` e `instr` podem custar muito dentro de uma única instrução do SQLite, onde o timeout não age.
  5. **Mascaramento**: toda coluna de saída que depende de uma coluna sensível (direto, por alias, expressão, subconsulta, CTE ou `UNION`) volta como `***`.
- O SQL executado é o regenerado a partir da árvore validada, e volta no campo `executed_sql`. Por isso, os nomes das colunas de saída vêm em minúsculas.
- A suíte de ataque em [`tests/test_attacks.py`](tests/test_attacks.py) tem 61 SQLs maliciosos (injeção, instruções empilhadas, escrita disfarçada, `ATTACH`, `PRAGMA`, funções perigosas, consultas caras e tentativas de ler colunas mascaradas). Para cada um, ela registra a camada que bloqueia e as camadas internas que ainda bloqueariam se as de fora falhassem, e testa as duas coisas.
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
| `run_query` | `sql` | Executa um `SELECT` (dialeto SQLite) e devolve `columns`, `rows`, `row_count`, `truncated`, `masked_columns`, `executed_sql` e o aviso de dados não confiáveis. Consulta bloqueada vira erro da tool com a camada que bloqueou, por exemplo `Query rejected (ast): ...`. |

Funções permitidas em `run_query`: agregações (`count`, `sum`, `avg`, `min`, `max`, `total`, `group_concat`), texto (`lower`, `upper`, `length`, `substr`, `trim`, `replace`, `instr`, `like`, `glob`), números (`abs`, `round`), nulos (`coalesce`, `ifnull`, `nullif`, `iif`), datas (`date`, `time`, `datetime`, `julianday`, `strftime`, `unixepoch`), `typeof` e as funções de janela (`row_number`, `rank`, `lag`, `lead` etc.). A lista completa está em `ALLOWED_FUNCTIONS`, em `src/sqlite_consulta/query.py`.

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
