# mcp-labs

Monorepo de estudo e construção de servidores MCP (Model Context Protocol) em Python, seguindo padrões profissionais: ambiente reproduzível, qualidade automatizada, decisões documentadas e fluxo de PR.

Cada servidor fica em `servers/<nome>/`.

| Servidor | O que faz | Estado |
|----------|-----------|--------|
| [`sqlite-consulta`](servers/sqlite-consulta/README.md) | Assistente de dados text-to-SQL seguro sobre o banco Chinook (SQLite) | fase 1 do [Roadmap](#roadmap) |

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

As mesmas verificações (exceto o pre-commit) rodam no CI, no job `quality`, em todo PR; lá o `pytest` também exige cobertura mínima de 80% do `sqlite-consulta` (ADR-0002). O job `secrets` roda o [gitleaks](https://github.com/gitleaks/gitleaks) sobre todo o histórico do repositório; o mesmo gitleaks roda no pre-commit sobre o que está em stage ([ADR-0011](docs/adr/0011-gitleaks-contra-vazamento-de-segredos.md)). Na primeira execução, o pre-commit instala o Go para compilar o gitleaks, o que leva alguns minutos.

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

As instruções para agentes (Codex e Claude Code) estão em [AGENTS.md](AGENTS.md), em inglês; o `CLAUDE.md` apenas importa esse arquivo.

## Skills e agents

| Nome | Tipo | Para que serve |
|------|------|----------------|
| `new-mcp-server` | skill | Cria um servidor MCP em `servers/<nome>/` no padrão do repositório |
| `new-adr` | skill | Cria um ADR numerado em `docs/adr/` |
| `reviewer` | agent (só Claude Code) | Revisa o diff contra as convenções e o checklist de segurança, sem editar arquivos |

Os arquivos ficam em `.claude/skills/` e `.claude/agents/`, no padrão aberto Agent Skills (`SKILL.md`).

### Claude Code

Não há o que instalar: o Claude Code carrega `.claude/skills/` e `.claude/agents/` quando é aberto na raiz do repositório.

- Skills: `/new-mcp-server` e `/new-adr`, ou um pedido em linguagem natural que corresponda à descrição da skill.
- Agent: peça, por exemplo, "use o agent reviewer para revisar o diff desta branch".

### Codex

O Codex lê skills de `.agents/skills/`, não de `.claude/skills/`. Para expor as mesmas skills sem duplicar arquivos, crie uma junção local, uma vez por clone, no PowerShell e na raiz do repositório:

```powershell
New-Item -ItemType Directory -Force .agents
New-Item -ItemType Junction -Path .agents\skills -Target .claude\skills
```

A pasta `.agents/` está no `.gitignore` e não é versionada. Em macOS ou Linux, crie um link simbólico equivalente de `.agents/skills` para `../.claude/skills`.

- Skills: `$new-mcp-server` e `$new-adr`; `/skills` lista as skills disponíveis.
- Diferença: o Codex não tem um equivalente ao agent `reviewer` neste repositório. Para revisar, peça ao Codex que siga o checklist de `.claude/agents/reviewer.md`.

### Skill externa: `translate-to-english`

O fluxo de duas fases para skills e agents (ADR-0006) usa a skill `translate-to-english`, que fica no repositório [AlexandreJareck/skill-labs](https://github.com/AlexandreJareck/skill-labs), e não aqui. Instale-a no nível do usuário: em `~/.claude/skills/translate-to-english/` para o Claude Code e em `~/.agents/skills/translate-to-english/` para o Codex.

## Roadmap

| Fase | Entrega | O que se aprende |
|------|---------|------------------|
| 1 | Servidor básico com Chinook: listar tabelas, descrever schema e amostrar linhas, sem SQL livre | tools, stdio |
| 2 | Tool de SQL com validação por AST, somente leitura, mascaramento e suíte de ataque | segurança |
| 3 | Resources, log de auditoria, limites configuráveis, HTTP com token e confirmação humana | resources, observabilidade, transportes |
| 4 | RAG local sobre schema e dicionário de dados, com busca híbrida | embeddings, recuperação |

O desenho do `sqlite-consulta` está no Design Doc [0001](docs/design/0001-sqlite-consulta.md). O harness de avaliação e o experimento de fine-tuning saíram do roadmap ([ADR-0010](docs/adr/0010-remocao-do-harness-de-avaliacao-e-fine-tuning.md)).
