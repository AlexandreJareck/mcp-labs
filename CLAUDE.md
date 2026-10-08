# mcp-labs

Monorepo de estudo e construção de servidores MCP em Python. Cada servidor fica em `servers/<nome>/`.

## Comandos
- Instalar: `uv sync --all-groups` e `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`
- Lint: `uv run ruff check .`; formatação: `uv run ruff format .`
- Tipos: `uv run mypy`
- Testes: `uv run pytest`
- Antes de commitar, os quatro devem passar.

## Convenções
- Python 3.12+, layout `src/`, tipos em todo o código (`mypy --strict`), docstrings estilo Google.
- Código, identificadores e mensagens de commit em inglês. Docs, ADRs e descrições de PR em português.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `build:`, `test:`, `refactor:`).
- Sem commit direto na `main`: branch curta e PR.
- Servidor MCP com transporte stdio: nunca usar `print()`. O stdout é o canal do protocolo. Logs via `logging` para stderr.
- Nenhum segredo no código. Configuração por variável de ambiente.
- Dependência nova: `uv add`, e o `uv.lock` vai no commit.

## Decisões e documentação
- Decisão técnica relevante: ADR em `docs/adr/` (skill `new-adr`).
- Mudança que envolve segurança, mais de um componente ou mais de um dia de trabalho: Design Doc em `docs/design/` antes de codar.
- Todo servidor tem `README.md` com: o que faz, como rodar e quais tools/resources expõe.

## Novo servidor
Use a skill `new-mcp-server`. Não crie servidores à mão.

## Skills e agents
Toda skill ou agent novo ou alterado em `.claude/` passa por duas fases (ADR-0006):
1. Redigir em pt-BR e submeter à revisão do usuário, que aprova ou pede alterações.
2. Só após a aprovação, traduzir para inglês com a skill `translate-to-english`, sem mudar o conteúdo.

Modelos e textos que a skill gera para o usuário (README de servidor, ADR, relatório de revisão) continuam em português, mesmo com a skill em inglês.

## Definição de pronto
Lint, formatação, tipos e testes passando; docs atualizadas; ADR ou Design Doc quando a regra pedir; revisão do agent `reviewer` sem achados bloqueantes.
