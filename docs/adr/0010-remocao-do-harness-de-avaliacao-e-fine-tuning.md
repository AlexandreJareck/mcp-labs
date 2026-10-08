# 0010. Remoção do harness de avaliação e do fine-tuning do roadmap

## Status

Proposto

## Data

2026-10-08

## Contexto

O roadmap inicial do `mcp-labs` previa a fase 5 (harness de avaliação) e a fase 6 (experimento de fine-tuning). Ambas exigem chamar LLMs fora da sessão do agente ou treinar modelos, o que tem custo ou exige contas e chaves, e a regra do projeto é não gastar além do uso normal da sessão. O servidor `sqlite-consulta` também nunca chama um LLM: quem escreve o SQL é o cliente MCP.

## Decisão

- Remover as fases "Harness de avaliação" e "Experimento de fine-tuning" do roadmap do `README.md`.
- O roadmap passa a ter só as fases 1 a 4 do `sqlite-consulta` (tools, segurança, resources e limites, RAG).
- A qualidade continua medida por testes determinísticos, incluindo a suíte de ataque e testes de relevância da busca da fase 4.

## Consequências

- Escopo menor e sem custo fora da sessão.
- Não haverá medição automatizada da qualidade do SQL gerado pelo modelo; ela fica restrita aos testes manuais com um cliente real.
- Reintroduzir essas fases exige um novo ADR, que substitua este.

## Alternativas consideradas

- **Manter as fases com modelos locais (por exemplo, Ollama):** proibido pelas regras de custo e uso de LLM do projeto.
- **Manter as fases no roadmap sem data:** deixaria o roadmap prometendo algo que não será feito.
