---
name: new-adr
description: Creates a numbered ADR in docs/adr/. Use when a relevant technical decision is made.
---

# New ADR

Records a technical decision in `docs/adr/`, following ADR-0005.

## Procedure

1. Confirm the decision's title with the user, if it is not already clear.
2. List `docs/adr/` and find the highest number used in `NNNN-*.md` files. The next free number is that value plus 1, with four digits (`0006`, `0007`...). Never reuse a number.
3. Generate the slug from the title: lowercase, no accents, words separated by hyphens (e.g., "Uso de sqlglot para validar SQL" becomes `uso-de-sqlglot-para-validar-sql`).
4. Copy `docs/adr/0000-template.md` to `docs/adr/NNNN-slug.md` and fill in:
   - title `# NNNN. <Título>`;
   - **Status:** `Proposto`;
   - **Data:** today's date (`AAAA-MM-DD`);
   - Contexto, Decisão, Consequências and Alternativas consideradas, in Portuguese, based on the conversation. Keep it to about half a page.
5. If the ADR supersedes another one, change the old one's status to `Substituído por [NNNN](NNNN-slug.md)`.
6. Remind the user to change the status to `Aceito` when the decision is confirmed, and to include the ADR in the PR for the change.
