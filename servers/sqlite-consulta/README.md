# sqlite-consulta

Assistente de dados text-to-SQL seguro sobre o banco de exemplo Chinook (SQLite).

O SQL é escrito pelo cliente MCP (por exemplo, o Claude Code). O servidor fornece contexto, valida e executa com segurança, e nunca chama um LLM. O desenho completo e o modelo de ameaças estão no [Design Doc 0001](../../docs/design/0001-sqlite-consulta.md).

**Estado atual: fase 4.** Além de listar tabelas, descrever o schema, ver algumas linhas e executar SQL livre de leitura (`run_query`, protegido em camadas), o servidor expõe o schema e o dicionário de dados como resources, registra cada consulta num log de auditoria, aceita limites por variável de ambiente, pede confirmação humana para consultas caras, pode rodar por HTTP local com token e busca contexto para uma pergunta (`search_context`) com RAG local.

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
| `SQLITE_CONSULTA_TIMEOUT_MS` | `2000` | Timeout de cada consulta, de 50 a 10000 ms. |
| `SQLITE_CONSULTA_MAX_ROWS` | `200` | Máximo de linhas por consulta, de 1 a 1000. |
| `SQLITE_CONSULTA_CONFIRM_COST` | `1000000` | Custo estimado (linhas examinadas) acima do qual o usuário precisa confirmar a consulta. |
| `SQLITE_CONSULTA_HTTP_TOKEN` | sem padrão | Token do transporte HTTP, com no mínimo 16 caracteres. Obrigatório só em HTTP; nunca o versione nem o coloque em arquivo do repositório. |

Valor inválido ou fora da faixa faz o servidor sair com código 1 e uma mensagem que cita o nome da variável (nunca o valor).

## Como obter o modelo de embeddings

A tool `search_context` usa um modelo multilíngue local (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, cerca de 250 MB, licença Apache-2.0), baixado uma vez do Hugging Face, sem conta nem token:

```bash
uv run sqlite-consulta download-model
```

O modelo fica em `models/` dentro de `SQLITE_CONSULTA_DATA_DIR`. O servidor nunca baixa o modelo sozinho: sem ele, `search_context` responde pedindo para rodar `download-model`, e as outras tools continuam funcionando. Decisão no [ADR-0014](../../docs/adr/0014-modelo-multilingue-e-busca-hibrida-com-rrf.md).

## Como rodar

```bash
uv run sqlite-consulta
```

O servidor fala MCP por stdio: ele fica aguardando mensagens JSON-RPC no stdin. Para testá-lo de forma interativa, conecte-o a um cliente MCP (abaixo). Antes de iniciar, ele confere o SHA-256 do banco; se o arquivo não existir ou não bater, sai com código 1 e pede para rodar `download-db`.

`uv run sqlite-consulta --help` mostra os subcomandos (`serve`, o padrão, e `download-db`).

### Transporte HTTP

O stdio é o padrão. Para HTTP, defina o token numa variável de ambiente da sua sessão (por exemplo, gerado com `python -c "import secrets; print(secrets.token_urlsafe(32))"`) e rode:

```bash
uv run sqlite-consulta serve --transport http --port 8123
```

O servidor escuta só em `127.0.0.1`, no caminho `/mcp`. Requisição sem token ou com token errado recebe 401; requisição com `Host` diferente de `127.0.0.1`/`localhost` recebe 421, mesmo com token (proteção contra DNS rebinding). Sem `SQLITE_CONSULTA_HTTP_TOKEN`, o servidor não inicia em HTTP. Decisão no [ADR-0012](../../docs/adr/0012-transporte-http-local-com-bearer-token-estatico.md).

### Log de auditoria

Cada chamada de `run_query` gera uma linha JSON no **stderr** (nunca no stdout, que é o canal do protocolo), com `timestamp`, `tool`, `sql_normalized`, `decision` (`allowed`, `rejected`, `confirmed`, `declined` ou `failed`), `reason`, `duration_ms`, `row_count` e `estimated_cost`. No SQL registrado, literais (texto, número, blob hexadecimal e booleano) e identificadores entre aspas viram `?`, porque podem conter dados pessoais (o SQLite lê um nome desconhecido entre aspas duplas como texto); SQL que não pode ser analisado não é registrado. Valores de resultado nunca são registrados. Exemplo:

```json
{"timestamp":"2026-10-09T23:45:45.919+00:00","event":"query","tool":"run_query","sql_normalized":"SELECT Name FROM Artist WHERE ArtistId = ?","decision":"allowed","reason":"","duration_ms":5.3,"row_count":1,"estimated_cost":2}
```

### Confirmação de consultas caras

Antes de executar, `run_query` estima o custo pelo `EXPLAIN QUERY PLAN` do SQLite. Acima de `SQLITE_CONSULTA_CONFIRM_COST`, o servidor pede confirmação ao usuário por **elicitation** (o mecanismo oficial do MCP), com o custo estimado e os limites. A consulta só roda se o usuário aceitar. Recusa, cancelamento ou cliente sem suporte a elicitation fazem a consulta não rodar.

A estimativa é aproximada: varredura completa custa o número de linhas da tabela, laços aninhados multiplicam, busca por igualdade custa 1 em chave única e, em coluna não única, o tamanho do maior grupo de valores iguais; busca por faixa (`>`, `<`, `BETWEEN`) custa a tabela inteira; e uma lista `IN (subconsulta)` custa o tamanho da tabela que a alimenta. CTE recursiva não tem tamanho conhecido e sempre pede confirmação. A estimativa decide quando perguntar; a proteção que sempre vale é o timeout e os limites de tamanho. Decisão no [ADR-0013](../../docs/adr/0013-confirmacao-humana-por-elicitation-com-resolver.md).

Comportamento observado no Claude Code 2.1.84 (Windows): no `claude` do terminal, o pedido aparece e, ao aceitar, a consulta roda; no app desktop, o pedido não é mostrado e a consulta cara é recusada (falha segura).

## Tools

Todas são somente leitura (`read_only_hint`) e devolvem saída estruturada.

| Tool | Argumentos | Descrição |
|------|-----------|-----------|
| `list_tables` | nenhum | Tabelas do banco com a contagem de linhas. |
| `describe_table` | `table` | Colunas (tipo, `NOT NULL`, chave primária, se é sensível) e chaves estrangeiras. |
| `sample_rows` | `table` | Até 5 linhas, com as colunas sensíveis mascaradas; `row_count` e `truncated` indicam quantas vieram e se a tabela tem mais. |
| `search_context` | `question`, `k` (1 a 10, padrão 5) | Devolve os trechos mais relevantes para uma pergunta, em português ou inglês: tabelas do dicionário de dados (descrição e colunas) e perguntas de exemplo com o SQL correspondente. Cada trecho traz `score` e as posições na busca lexical (`lexical_rank`) e vetorial (`vector_rank`). Use antes de escrever o SQL. |
| `run_query` | `sql` | Executa um `SELECT` (dialeto SQLite) e devolve `columns`, `rows`, `row_count`, `truncated`, `masked_columns`, `executed_sql` e o aviso de dados não confiáveis. Consulta bloqueada vira erro da tool com a camada que bloqueou, por exemplo `Query rejected (ast): ...`. |

Funções permitidas em `run_query`: agregações (`count`, `sum`, `avg`, `min`, `max`, `total`, `group_concat`), texto (`lower`, `upper`, `length`, `substr`, `trim`, `replace`, `instr`, `like`, `glob`), números (`abs`, `round`), nulos (`coalesce`, `ifnull`, `nullif`, `iif`), datas (`date`, `time`, `datetime`, `julianday`, `strftime`, `unixepoch`), `typeof` e as funções de janela (`row_number`, `rank`, `lag`, `lead` etc.). A lista completa está em `ALLOWED_FUNCTIONS`, em `src/sqlite_consulta/query.py`.

### Como funciona a busca de contexto

- Fontes versionadas, dentro do pacote: `data_dictionary.json` (um trecho por tabela) e `examples.json` (21 perguntas em português com o SQL, todas validadas pelas camadas de proteção e testadas contra o Chinook).
- Busca **lexical** com BM25 (sem acentos, com nomes em camelCase separados, como `InvoiceLine` em `invoice line`) e busca **vetorial** com os embeddings do modelo local, combinadas por *Reciprocal Rank Fusion*.
- O índice é montado em memória no primeiro uso (cerca de 2 s com o modelo em cache); nada derivado é versionado.

## Resources

| URI | Conteúdo |
|-----|----------|
| `sqlite-consulta://schema` | Schema em JSON: tabelas, colunas, tipos, chaves e quais colunas são sensíveis. |
| `sqlite-consulta://dictionary` | Dicionário de dados em JSON: descrição de cada tabela e coluna (arquivo versionado `src/sqlite_consulta/data_dictionary.json`), contagem de linhas e sensibilidade. |

## Como conectar ao Claude

Claude Code (na raiz do repositório):

```bash
claude mcp add sqlite-consulta -- uv run --directory <caminho-absoluto-do-repo> sqlite-consulta
claude mcp list
```

O `claude mcp list` deve mostrar `sqlite-consulta: ... - ✓ Connected`. Rode `download-db` antes; sem o banco, o servidor não inicia.

Por HTTP, com o servidor rodando como acima e o token na variável `SQLITE_CONSULTA_HTTP_TOKEN` do seu terminal (em PowerShell, `$env:SQLITE_CONSULTA_HTTP_TOKEN`):

```bash
claude mcp add --transport http sqlite-consulta-http http://127.0.0.1:8123/mcp --header "Authorization: Bearer $SQLITE_CONSULTA_HTTP_TOKEN"
```

O Claude Code guarda o cabeçalho na sua configuração local (`~/.claude.json`), fora do repositório.

## Testes

Os testes usam um banco pequeno criado no próprio teste e não dependem do download. Na raiz do repositório:

```bash
uv run pytest servers/sqlite-consulta --cov=sqlite_consulta --cov-report=term-missing
```

O CI exige cobertura mínima de 80% para este servidor. Os testes de relevância de `search_context` (`tests/test_rag_relevance.py`) usam o modelo real: localmente, são pulados se o modelo não foi baixado; no CI, o modelo é baixado (e guardado em cache) e `SQLITE_CONSULTA_REQUIRE_MODEL=1` faz a falta do modelo falhar em vez de pular.
