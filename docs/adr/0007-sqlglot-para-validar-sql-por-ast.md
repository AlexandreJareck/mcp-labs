# 0007. sqlglot para validar SQL por AST

## Status

Proposto

## Data

2026-10-08

## Contexto

A partir da fase 2, o `sqlite-consulta` executa SQL escrito pelo cliente MCP, que pode ter sido manipulado por prompt injection. É preciso garantir que só passe um único `SELECT`, sem escrita, DDL, `PRAGMA` ou `ATTACH`, e descobrir quais colunas de saída dependem de colunas sensíveis, inclusive via alias, expressão, subconsulta, CTE ou `UNION` (Design Doc 0001).

## Decisão

- Usar o [`sqlglot`](https://sqlglot.com/) (licença MIT, Python puro, sem serviço externo) para fazer o parse do SQL no dialeto `sqlite` e validar a **árvore sintática (AST)**: exatamente uma instrução, raiz `SELECT` ou operação de conjunto de `SELECT`s, nenhum nó de escrita, DDL ou `Command`, e funções só de uma allowlist.
- Usar o qualificador de colunas do `sqlglot` com o schema real do banco para rastrear a linhagem de cada coluna de saída e decidir o mascaramento.
- O parser é **uma** das camadas: a decisão final de permitir leitura é do próprio SQLite (`mode=ro`, `query_only` e `set_authorizer`).
- A versão é fixada pelo `uv.lock`; a API é conferida na documentação atual antes de usar.

## Consequências

- Validação estrutural, imune a truques de maiúsculas, comentários e espaços que derrubam regex.
- Dependência nova, com releases frequentes; atualizações exigem rodar a suíte de ataque.
- O dialeto do `sqlglot` pode divergir do SQLite real em casos raros; por isso SQL que o parser não entende é rejeitado e o authorizer cobre o que escapar.

## Alternativas consideradas

- **Regex ou lista de palavras proibidas:** frágil e fácil de contornar.
- **`sqlparse`:** tokenizador sem AST semântica nem qualificação de colunas; não resolve o mascaramento por linhagem.
- **Só `set_authorizer`:** bloqueia escrita, mas não enxerga aliases e expressões para mascarar a saída.
