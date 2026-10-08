# 0006. Skills e agents em duas fases: revisão em pt-BR e tradução para inglês

## Status

Aceito

## Data

2026-10-08

## Contexto

As skills e os agents em `.claude/` são instruções para o modelo. O usuário revisa melhor em português, mas o ADR-0003 define inglês para artefatos técnicos, e instruções em inglês seguem o padrão das documentações oficiais e das skills públicas. Escrever direto em inglês dificulta a revisão; manter em português destoa do resto do código.

## Decisão

- Toda skill ou agent novo ou alterado passa por duas fases:
  1. **Redação em pt-BR**, submetida à revisão do usuário, que aprova ou pede alterações.
  2. **Tradução para inglês** só após a aprovação, com a skill `translate-to-english`, preservando exatamente o conteúdo aprovado.
- O que a skill **gera para o usuário** continua em português (ADR-0003): modelos de README de servidor, ADRs, Design Docs e relatórios de revisão. Esses modelos não são traduzidos.
- Nomes de skills e agents são identificadores e, como tal, ficam em inglês (`new-mcp-server`, `new-adr`, `reviewer`).

## Consequências

- O conteúdo é discutido no idioma de quem revisa, e o arquivo final segue o padrão de mercado.
- Qualquer mudança de conteúdo depois da tradução exige uma nova rodada: alterar em pt-BR, aprovar e traduzir de novo.
- A `translate-to-english` vive em outro repositório (`POCS/skill-labs`) e precisa estar instalada no ambiente de quem faz a tradução.

## Alternativas consideradas

- **Tudo em pt-BR:** revisão fácil, mas fora do padrão do ADR-0003 para artefatos técnicos.
- **Escrever direto em inglês:** dispensa a tradução, mas torna a revisão mais lenta e sujeita a mal-entendidos.
