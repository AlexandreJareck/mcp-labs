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
- PR titles in English, following Conventional Commits (e.g., `feat(sqlite-consulta): add AST validation and attack suite`): the squash merge turns the title into the commit message on `main` (ADR-0003).
- No direct commits to `main`: short-lived branch and PR.
- MCP server with stdio transport: never use `print()`. stdout is the protocol channel. Logs via `logging` to stderr.
- No secrets in the code. Configuration via environment variables.
- **Absolute secrets rule:** never publish to GitHub any token, key, password, secret, or credential, whether real or realistic-looking. No exceptions, not even for tests, examples, documentation, or "temporary" values.
  - Applies to code, tests, fixtures, docs, READMEs, ADRs, Design Docs, commit messages, PR descriptions, comments, issues, and CI output.
  - Secrets exist only in environment variables on the local machine. Document only the variable's **name**, never its value. `.env` files are never versioned.
  - In tests, generate fake values at runtime (e.g., `secrets.token_urlsafe()`); never write anything that looks like a real token.
  - Never display secrets in chat, reports, the audit log, or error messages.
  - Before every commit and every push, review the diff (`git diff --cached`) and run gitleaks (pre-commit hook; CI job `secrets` scans the full history).
  - If GitHub push protection blocks a push, never bypass it or mark it as a false positive: stop and notify the user.
  - If a secret gets into a commit, stop and do not push. If it was already published, notify the user immediately so it can be revoked and rotated; treat it as compromised. Do not rewrite history without explicit authorization.
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
