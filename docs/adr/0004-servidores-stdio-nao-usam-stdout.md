# 0004. Servidores MCP stdio não usam stdout

## Status

Aceito

## Data

2026-10-08

## Contexto

No transporte stdio, o cliente MCP troca mensagens JSON-RPC com o servidor pelo stdin e pelo stdout do processo. Qualquer texto solto escrito no stdout (um `print()` de depuração, por exemplo) corrompe o fluxo e quebra a conexão, com erros difíceis de diagnosticar.

## Decisão

- Servidores MCP com transporte stdio **nunca** escrevem no stdout fora do SDK.
- Logs usam o módulo `logging`, configurado para **stderr**.
- A regra `T20` do ruff proíbe `print()` em todo o código e faz cumprir esta decisão automaticamente.

## Consequências

- Uma classe inteira de erro é eliminada antes do commit.
- Em um script que realmente precise de `print()` (fora de servidores), a exceção deve ser explícita (`# noqa: T201`) e justificada na revisão.

## Alternativas consideradas

- **Confiar em revisão manual:** falha com facilidade, especialmente com código de depuração esquecido.
