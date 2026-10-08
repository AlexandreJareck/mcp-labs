# 0002. Qualidade automatizada

## Status

Aceito

## Data

2026-10-08

## Contexto

Servidores MCP expõem ferramentas a modelos de linguagem e, no futuro, acesso a dados. Erros de tipo, falhas de segurança e regressões precisam ser pegos antes do merge, sem depender só de revisão manual.

## Decisão

- **ruff** para lint e formatação, incluindo as regras de segurança `S` (derivadas do bandit) e a regra `T20` (proíbe `print`).
- **mypy** em modo `strict` sobre todo o código e testes; cada servidor é adicionado a `[tool.mypy] files`.
- **pytest** para testes, com cobertura mínima de **80% por servidor**, exigida a partir do primeiro servidor (o `pytest-cov` já está instalado).
- **pre-commit** como primeira barreira local (ruff, mypy, verificações de arquivo e da mensagem de commit).
- **CI no GitHub Actions** como barreira final: o job `quality` roda lint, formatação, tipos e testes em todo PR.

## Consequências

- Código que não passa nas verificações não entra na `main`.
- Tipos em todo o código aumentam o esforço inicial, mas tornam as tools MCP mais previsíveis.
- O limite de cobertura será configurado junto com o primeiro servidor.

## Alternativas consideradas

- **black + flake8 + isort:** três ferramentas com configurações separadas para o que o ruff faz sozinho e mais rápido.
- **pyright:** bom verificador, mas o mypy tem modo `strict` bem documentado e se integra facilmente ao pre-commit e ao CI via `uv run`.
