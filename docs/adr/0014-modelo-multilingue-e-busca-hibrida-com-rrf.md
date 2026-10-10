# 0014. Modelo de embeddings multilíngue e busca híbrida com RRF

## Status

Proposto

## Data

2026-10-10

## Contexto

O ADR-0008 escolheu o `fastembed` e deixou para a fase 4 a escolha do modelo: o padrão `BAAI/bge-small-en-v1.5` só entende inglês, e as perguntas do usuário vêm em português, enquanto o dicionário de dados está em inglês. A busca precisa funcionar offline, sem custo e nos testes do CI.

## Decisão

- Modelo: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensões, cerca de 250 MB em disco, licença Apache-2.0), baixado do repositório público `Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q` no Hugging Face, sem conta nem token.
- O download só acontece pelo comando `sqlite-consulta download-model`, para `models/` dentro de `SQLITE_CONSULTA_DATA_DIR`. Em execução, o servidor usa `local_files_only=True`: sem o modelo, a tool responde pedindo o download, nunca baixa sozinha.
- Busca híbrida: BM25 próprio (tokenização sem acentos, com camelCase separado e stopwords em português e inglês) + similaridade de cosseno dos embeddings, combinados por Reciprocal Rank Fusion (`k = 60`).
- Fontes versionadas: `data_dictionary.json` (um trecho por tabela) e `examples.json` (um trecho por pergunta de exemplo com o SQL). O índice é montado em memória no primeiro uso; nada derivado é versionado.

## Consequências

- Perguntas em português encontram tabelas descritas em inglês; nas perguntas de teste, o trecho esperado fica entre os três primeiros.
- O primeiro uso exige rede e cerca de 250 MB; o CI guarda o modelo em cache entre execuções.
- O modelo não tem hash fixado como o banco (ADR-0009): a integridade depende do Hugging Face e da revisão `main` do repositório. Aceito para um modelo público, de uso local e sem acesso a dados. Uma mudança no repositório de origem pode alterar o ranking e quebrar os testes de relevância sem mudança no código; o cache do CI é invalidado junto com o `uv.lock`.

## Alternativas consideradas

- **`BAAI/bge-small-en-v1.5` (padrão):** menor, mas só inglês; falha em perguntas em português sem vocabulário em comum.
- **`intfloat/multilingual-e5-large`:** melhor qualidade, mas 2,2 GB, pesado para o CI.
- **Só busca vetorial:** perde nomes exatos de tabelas e colunas, que o BM25 acerta.
- **Somar notas normalizadas em vez de RRF:** exige calibrar escalas diferentes; o RRF só usa as posições.
