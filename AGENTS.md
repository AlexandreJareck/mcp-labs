# mcp-labs

Monorepo for studying and building MCP servers in Python. Each server lives in `servers/<nome>/`.

## Commands
- Install: `uv sync --all-groups` and `uv run pre-commit install --hook-type pre-commit --hook-type commit-msg`
- Lint: `uv run ruff check .`; formatting: `uv run ruff format .`
- Types: `uv run mypy`
- Tests: `uv run pytest`
- Before committing, all four must pass.

## Conventions
- Python 3.12+, `src/` layout, types throughout the code (`mypy --strict`), Google-style docstrings.
- Code, identifiers, and commit messages in English. Docs, ADRs, and PR descriptions in Portuguese.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`, `build:`, `test:`, `refactor:`).
- No direct commits to `main`: short-lived branch and PR.
- MCP server with stdio transport: never use `print()`. stdout is the protocol channel. Logs via `logging` to stderr.
- No secrets in the code. Configuration via environment variables.
- New dependency: `uv add`, and `uv.lock` goes into the commit.

## Decisions and documentation
- Relevant technical decision: ADR in `docs/adr/` (skill `new-adr`).
- Change involving security, more than one component, or more than one day of work: Design Doc in `docs/design/` before coding.
- Every server has a `README.md` with: what it does, how to run it, and which tools/resources it exposes.

## New server
Use the skill `new-mcp-server`. Do not create servers by hand.

## Skills and agents
Every new or changed skill or agent in `.claude/` goes through two phases (ADR-0006):
1. Write it in pt-BR and submit it for the user's review; the user approves it or requests changes.
2. Only after approval, translate it into English with the skill `translate-to-english`, without changing the content.

Templates and text that the skill generates for the user (server README, ADR, review report) remain in Portuguese, even with the skill in English.

## Definition of done
Lint, formatting, types, and tests passing; docs updated; ADR or Design Doc when the rule requires it; review by the `reviewer` agent with no blocking findings.
