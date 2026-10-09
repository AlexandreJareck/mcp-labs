# 0012. Transporte HTTP local com bearer token estático

## Status

Proposto

## Data

2026-10-09

## Contexto

A fase 3 do `sqlite-consulta` adiciona o transporte HTTP (Streamable HTTP), mantendo o stdio como padrão. Em HTTP, qualquer processo local ou página web pode tentar falar com o servidor. As regras do projeto proíbem deploy, hospedagem, túnel público e serviços pagos, então não há servidor de autorização OAuth disponível.

## Decisão

- HTTP só com `serve --transport http`, sempre em `127.0.0.1` (não há opção de host) e porta entre 1024 e 65535.
- Autenticação por **bearer token estático**, lido de `SQLITE_CONSULTA_HTTP_TOKEN` (mínimo de 16 caracteres). Sem a variável, o servidor não inicia em HTTP.
- O token é verificado por um `TokenVerifier` próprio, que compara em tempo constante (`hmac.compare_digest`), plugado no `MCPServer` com `AuthSettings`. Como não existe servidor de autorização, `issuer_url` aponta para o próprio servidor local e `validate_token_resource` fica desligado (o verificador já confere o token inteiro).
- A proteção contra DNS rebinding do SDK continua ligada (o padrão para localhost): `Host` diferente de `127.0.0.1:<porta>`/`localhost:<porta>` recebe 421.
- O token nunca aparece em log, erro, `repr` ou documentação; mensagens citam só o nome da variável.

## Consequências

- Requisição sem token ou com token errado recebe 401; o Claude Code conecta com `claude mcp add --transport http ... --header "Authorization: Bearer ..."`.
- O token fica na configuração local do cliente; trocá-lo exige reiniciar o servidor e atualizar o cliente.
- Não há escopos nem expiração: suficiente para uso local, inadequado para exposição em rede.

## Alternativas consideradas

- **OAuth 2.1 completo:** exige um servidor de autorização, fora do escopo e das regras de custo.
- **HTTP sem autenticação em localhost:** outros processos locais e páginas web (via DNS rebinding) poderiam consultar o banco.
- **Escutar em `0.0.0.0`:** exporia o servidor na rede; proibido pelas regras do projeto.
