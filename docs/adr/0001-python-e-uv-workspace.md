# 0001. Python 3.12+ e uv como gerenciador e workspace

## Status

Aceito

## Data

2026-10-08

## Contexto

O repositório vai abrigar vários servidores MCP independentes. Cada um precisa de dependências próprias, mas todos devem compartilhar as mesmas ferramentas de qualidade e um ambiente reproduzível em qualquer máquina e no CI.

## Decisão

- Python 3.12 ou superior, com layout `src/` em cada servidor.
- `uv` como gerenciador de Python, dependências e ambiente virtual.
- Workspace do `uv`: a raiz é um projeto não publicado (`package = false`) e cada servidor em `servers/<nome>/` é um membro.
- Um único `uv.lock` na raiz, versionado, fixa as versões de todo o monorepo. O CI usa `uv sync --locked`.

## Consequências

- Instalação em um comando (`uv sync --all-groups`) e ambiente idêntico local e no CI.
- Os servidores compartilham um único lock, então não podem usar versões conflitantes de uma mesma dependência; isso é aceitável em um repositório de estudo.
- Dependência nova sempre via `uv add`, com o `uv.lock` no mesmo commit.

## Alternativas consideradas

- **Poetry:** maduro, mas mais lento e não gerencia a versão do Python; suporte a monorepo menos direto.
- **pip + venv:** sem lock nativo nem workspace; a reprodutibilidade dependeria de disciplina manual.
