# 0005. ADR e Design Doc

## Status

Aceito

## Data

2026-10-08

## Contexto

Decisões e desenhos precisam ficar registrados junto ao código, para que o raciocínio não se perca entre sessões de estudo.

## Decisão

- **ADR** (`docs/adr/`) registra **uma decisão** técnica relevante: contexto, decisão, consequências e alternativas. Numeração sequencial (`NNNN-slug.md`) a partir de `0000-template.md`, criado com a skill `new-adr`.
- **Design Doc** (`docs/design/`) descreve **como construir** algo **antes** de construir. É exigido quando a mudança envolve segurança, mais de um componente ou mais de um dia de trabalho. Segue `docs/design/0000-template.md`, com modelo de ameaças obrigatório quando envolve segurança ou dados.
- Um Design Doc costuma gerar ADRs, listados na sua seção final.

## Consequências

- Mudanças grandes começam por um documento curto, revisável no PR.
- Pequenas correções não exigem documento algum.

## Alternativas consideradas

- **Só ADR:** não comporta bem o desenho completo de um servidor, como o modelo de ameaças.
- **Wiki externa:** separa a documentação do código e não passa pelo PR.
