---
name: novo-adr
description: Cria um ADR numerado em docs/adr/. Use quando uma decisão técnica relevante for tomada.
---

# Novo ADR

Registra uma decisão técnica em `docs/adr/`, seguindo o ADR-0005.

## Procedimento

1. Confirme com o usuário o título da decisão, se ainda não estiver claro.
2. Liste `docs/adr/` e encontre o maior número usado em arquivos `NNNN-*.md`. O próximo número livre é esse valor mais 1, com quatro dígitos (`0006`, `0007`...). Nunca reutilize um número.
3. Gere o slug a partir do título: minúsculas, sem acentos, palavras separadas por hífen (ex.: "Uso de sqlglot para validar SQL" vira `uso-de-sqlglot-para-validar-sql`).
4. Copie `docs/adr/0000-template.md` para `docs/adr/NNNN-slug.md` e preencha:
   - título `# NNNN. <Título>`;
   - **Status:** `Proposto`;
   - **Data:** a data de hoje (`AAAA-MM-DD`);
   - Contexto, Decisão, Consequências e Alternativas consideradas, em português, com base na conversa. Mantenha em cerca de meia página.
5. Se o ADR substituir outro, mude o status do antigo para `Substituído por [NNNN](NNNN-slug.md)`.
6. Lembre o usuário de mudar o status para `Aceito` quando a decisão for confirmada, e de incluir o ADR no PR da mudança.
