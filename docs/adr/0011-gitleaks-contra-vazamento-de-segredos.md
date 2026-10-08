# 0011. gitleaks contra vazamento de segredos

## Status

Proposto

## Data

2026-10-08

## Contexto

O repositório é público e, a partir da fase 3, o `sqlite-consulta` usa um token para o transporte HTTP. A regra do projeto é absoluta: nenhum token, chave, senha ou credencial, real ou com aparência de real, pode chegar ao GitHub. O hook `detect-private-key` só pega chaves privadas, e o *secret scanning* do GitHub age depois do push ou só bloqueia padrões conhecidos.

## Decisão

- Adicionar o hook oficial `gitleaks` ([gitleaks/gitleaks](https://github.com/gitleaks/gitleaks), `v8.30.1`, última versão estável em 2026-10-08) ao `.pre-commit-config.yaml`, verificando o que está em stage antes de cada commit.
- No CI, um job `secrets` roda o mesmo gitleaks sobre **todo o histórico** (`fetch-depth: 0`). O binário é baixado da release oficial e verificado pelo SHA-256 publicado no arquivo de checksums da release, sem usar action de terceiros.
- Registrar a regra absoluta de segredos no `AGENTS.md`.

## Consequências

- Segredos são barrados localmente antes do commit e, se escaparem, o CI falha no PR.
- O hook `gitleaks` usa `language: golang`; o pre-commit instala o Go necessário na primeira execução, o que deixa essa execução mais lenta.
- Atualizar a versão exige mudar o `rev` do hook, a versão e o checksum no CI, juntos.

## Alternativas consideradas

- **`gitleaks/gitleaks-action`:** em PRs varre só os commits do PR, não o histórico inteiro, e exige licença em contas de organização.
- **Só o secret scanning do GitHub:** não roda localmente e cobre apenas padrões de provedores conhecidos.
- **`detect-secrets`:** exige manter um arquivo de baseline versionado, sem benefício claro sobre o gitleaks aqui.
