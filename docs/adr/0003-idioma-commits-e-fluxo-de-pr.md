# 0003. Idioma, commits e fluxo de PR

## Status

Aceito

## Data

2026-10-08

## Contexto

O repositório é de estudo e mantido por uma pessoa que prefere escrever em português, mas o código deve seguir o padrão de mercado e ser legível para qualquer pessoa.

## Decisão

- **Inglês** em código, identificadores e mensagens de commit.
- **Português** em documentação, ADRs, Design Docs e descrições de PR.
- Mensagens de commit no padrão **Conventional Commits**, verificado pelo hook `conventional-pre-commit`.
- Toda mudança passa por **branch curta e PR**; sem commit direto na `main` (exceção: o commit inicial).
- Merge por **squash**, para manter um commit por PR na `main`.

## Consequências

- Histórico da `main` limpo e legível.
- O aprendizado fica documentado no idioma de quem estuda.
- Exige a disciplina de abrir PR mesmo trabalhando sozinho.

## Alternativas consideradas

- **Tudo em português:** identificadores em português destoam das bibliotecas e da documentação oficial.
- **Tudo em inglês:** atrapalharia o registro do aprendizado.
