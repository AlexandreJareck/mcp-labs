# 0008. fastembed para embeddings locais

## Status

Aceito

## Data

2026-10-08

## Contexto

A fase 4 do `sqlite-consulta` faz RAG sobre o dicionário de dados e exemplos de perguntas, com busca híbrida (lexical e vetorial). A regra de custo do projeto proíbe APIs pagas ou com cota gratuita, e os testes precisam rodar no CI sem chave de API.

## Decisão

- Gerar embeddings localmente com o [`fastembed`](https://github.com/qdrant/fastembed) (licença Apache-2.0), que usa ONNX Runtime e não exige PyTorch nem GPU.
- Modelo inicial: o padrão da biblioteca, `BAAI/bge-small-en-v1.5` (384 dimensões), baixado uma vez de fonte pública, sem conta ou token, e mantido em cache local. A troca por um modelo multilíngue será avaliada na fase 4 (pergunta em aberto do Design Doc 0001).
- A parte lexical (BM25) é implementada localmente, sem serviço externo; os rankings são combinados por Reciprocal Rank Fusion.
- O índice é recriado a partir de arquivos versionados e não é versionado; o modelo também não.

## Consequências

- Zero custo e funcionamento offline após o primeiro download.
- O primeiro uso (e o CI sem cache) baixa o modelo; o CI deve guardar o cache entre execuções.
- O `onnxruntime` aumenta o tamanho do ambiente; aceitável para o estudo.

## Alternativas consideradas

- **APIs de embeddings (OpenAI, Voyage etc.):** violam a regra de custo e exigem chave no CI.
- **`sentence-transformers`:** exige PyTorch, muito maior para instalar no CI.
- **Ollama:** proibido pelas regras de custo do projeto e exige um serviço local extra.
- **Só busca lexical:** mais simples, mas não captura sinônimos e perguntas parafraseadas, que são o objetivo do aprendizado da fase.
