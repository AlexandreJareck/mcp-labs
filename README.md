# mcp-labs

Monorepo de estudo e construção de servidores MCP (Model Context Protocol) em Python, seguindo padrões profissionais: ambiente reproduzível, qualidade automatizada, decisões documentadas e fluxo de PR.

Cada servidor fica em `servers/<nome>/`. Ainda não há servidores; o primeiro será o `sqlite-consulta` (ver [Roadmap](#roadmap)).

## Pré-requisitos

- [uv](https://docs.astral.sh/uv/) (gerencia Python, dependências e ambiente virtual)
- Python 3.12 (instalável com `uv python install 3.12`)
- Git

## Instalação

```bash
uv sync --all-groups
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## Verificações

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run pre-commit run --all-files
```

As mesmas verificações (exceto o pre-commit) rodam no CI, no job `quality`, em todo PR.

## Estrutura

```
mcp-labs/
├── .claude/          # Claude Code: agent reviewer e skills new-mcp-server e new-adr
├── .github/          # CI (GitHub Actions) e template de PR
├── docs/
│   ├── adr/          # decisões de arquitetura (ADRs)
│   ├── design/       # Design Docs
│   └── estudos/      # anotações de aprendizado sobre MCP
├── servers/          # um servidor MCP por pasta
├── tests/            # testes das regras do repositório
├── pyproject.toml    # raiz do workspace uv e configuração das ferramentas
└── uv.lock           # versões fixadas de todo o monorepo
```

## Fluxo de trabalho

1. Crie uma branch curta a partir da `main` (por exemplo, `feat/sqlite-consulta`).
2. Faça commits em inglês, no padrão [Conventional Commits](https://www.conventionalcommits.org/) (verificado pelo hook `commit-msg`).
3. Decisão técnica relevante: registre um ADR em `docs/adr/` (skill `new-adr`).
4. Mudança que envolve segurança, mais de um componente ou mais de um dia de trabalho: escreva um Design Doc em `docs/design/` antes de codar.
5. Novo servidor: use a skill `new-mcp-server`.
6. Abra um PR para a `main` com descrição em português, peça a revisão do agent `reviewer` e faça merge por squash com o CI verde.

As convenções completas para o Claude Code estão em [CLAUDE.md](CLAUDE.md).

## Roadmap

| Fase | Entrega | O que se aprende |
|------|---------|------------------|
| 1 | Servidor básico com Chinook | tools, stdio |
| 2 | Validação por AST, somente leitura e suíte de ataque | segurança |
| 3 | Resources, log e limites | resources, observabilidade |
| 4 | RAG sobre schema e dicionário de dados | embeddings, recuperação |
| 5 | Harness de avaliação | medir de verdade |
| 6 | Experimento de fine-tuning | quando vale a pena |

O servidor `sqlite-consulta` começa pelo Design Doc `docs/design/0001-sqlite-consulta.md`.
