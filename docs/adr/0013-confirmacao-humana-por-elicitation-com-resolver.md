# 0013. Confirmação humana por elicitation com resolver

## Status

Aceito

## Data

2026-10-09

## Contexto

A fase 3 exige confirmação humana antes de consultas caras, usando o mecanismo oficial do MCP. O mecanismo é a **elicitation**: o servidor pede ao cliente que pergunte algo ao usuário. No SDK Python 2.x, `ctx.elicit` só funciona em conexões com protocolo até 2025-11-25; na versão 2026-07-28, o pedido é feito em várias idas e voltas, e o SDK oferece **resolvers** (`Resolve` + `Elicit`), que funcionam nas duas versões.

## Decisão

- A tool `run_query` declara um parâmetro resolvido (`Annotated[ElicitationResult[...], Resolve(...)]`), escondido do modelo: o modelo não consegue preencher a confirmação.
- O resolver estima o custo da consulta pelo `EXPLAIN QUERY PLAN` do SQLite: `SCAN` de tabela e busca por faixa em índice (`>`, `<`, `BETWEEN`) custam a tabela inteira, busca por igualdade custa 1 em chave única e o maior grupo de valores iguais em coluna não única, `IN (subconsulta)` custa a tabela que a alimenta, laços aninhados e subconsultas correlacionadas multiplicam, e CTE recursiva (tamanho desconhecido) é sempre considerada cara. Abaixo do limite (`SQLITE_CONSULTA_CONFIRM_COST`, padrão 1.000.000), não pergunta nada; acima, devolve `Elicit` com o custo estimado e os limites.
- **Falha fechada:** a consulta cara só roda com `accept` e `confirm=true`. Recusa, cancelamento, `confirm=false` ou cliente sem a capacidade de elicitation resultam em erro da tool, sem executar, e em uma linha de auditoria com a decisão.

## Consequências

- O usuário vê o pedido no cliente, e o modelo não consegue contorná-lo.
- A estimativa é aproximada: serve para decidir quando perguntar, não como limite de segurança. Timeout e limites de tamanho continuam valendo para toda consulta.
- Clientes sem elicitation não executam consultas caras; a mensagem orienta a reduzir o custo da consulta.
- O protocolo chama o resolver duas vezes por pedido (perguntar e repetir com a resposta), então a consulta é validada mais de uma vez; o custo é de milissegundos.

## Alternativas consideradas

- **`ctx.elicit` direto no corpo da tool:** falha em conexões 2026-07-28.
- **Parâmetro `confirm=true` na própria tool:** o modelo poderia preenchê-lo sozinho; não é confirmação humana.
- **Bloquear consultas caras sem perguntar:** mais simples, mas impede análises legítimas maiores.
