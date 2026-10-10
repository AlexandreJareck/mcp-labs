import hashlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from mcp import Client
from sqlite_consulta import chinook, dictionary, rag, server
from sqlite_consulta.query import validate


class FakeEmbedder:
    """Deterministic bag-of-words vectors: no model, no network."""

    dim = 64

    def __init__(self) -> None:
        self.passage_calls = 0

    def _vector(self, text: str) -> rag.Vector:
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in rag.tokenize(text):
            digest = hashlib.sha256(token.encode()).digest()
            vector[digest[0] % self.dim] += 1.0
        return vector

    def embed_passages(self, texts: Sequence[str]) -> list[rag.Vector]:
        self.passage_calls += 1
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> rag.Vector:
        return self._vector(text)


CHUNKS = [
    rag.Chunk("table:Track", "table", "Table Track", "Table Track: songs, duration, price"),
    rag.Chunk("table:Invoice", "table", "Table Invoice", "Table Invoice: purchases and totals"),
    rag.Chunk(
        "example:revenue",
        "example",
        "Faturamento por país",
        "Question: Faturamento por país\nSQL: SELECT BillingCountry, sum(Total) FROM Invoice",
    ),
]


# --- Tokenizer and BM25 ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("InvoiceLine", ["invoice", "line"]),
        ("Qual o faturamento de cada país?", ["faturamento", "pais"]),
        ("Músicas mais longas", ["musicas", "longas"]),
        ("SELECT sum(Total) FROM Invoice", ["select", "sum", "total", "invoice"]),
        ("a e o", []),
    ],
)
def test_tokenize(text: str, tokens: list[str]) -> None:
    assert rag.tokenize(text) == tokens


def test_bm25_prefers_documents_with_rare_matching_terms() -> None:
    bm25 = rag.BM25([["invoice", "total"], ["track", "price"], ["invoice", "line", "track"]])
    scores = bm25.scores(["price"])
    assert scores[1] > 0
    assert scores[0] == scores[2] == 0


def test_bm25_handles_empty_corpus() -> None:
    assert rag.BM25([]).scores(["x"]) == []


# --- Chunks and versioned files -------------------------------------------------------


def test_chunks_cover_every_table_and_example() -> None:
    chunks = rag.build_chunks()
    tables = [chunk for chunk in chunks if chunk.kind == "table"]
    examples = [chunk for chunk in chunks if chunk.kind == "example"]
    assert len(tables) == len(dictionary.load_source()["tables"]) == 11
    assert len(examples) == len(rag.load_examples()) >= 20
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    track = next(chunk for chunk in tables if chunk.id == "table:Track")
    assert "Milliseconds" in track.text


def test_chunks_are_reproducible() -> None:
    assert rag.build_chunks() == rag.build_chunks()


def _chinook_schema() -> dict[str, dict[str, str]]:
    source = dictionary.load_source()
    return {
        name: dict.fromkeys(table["columns"], "TEXT") for name, table in source["tables"].items()
    }


@pytest.mark.parametrize("example", rag.load_examples(), ids=lambda example: example["id"])
def test_every_example_passes_the_ast_layer(example: dict[str, str]) -> None:
    validated = validate(example["sql"], _chinook_schema())
    if example["id"] == "customer-contact-masked":
        assert validated.masked_positions == {2, 3}
    else:
        assert validated.masked_positions == frozenset()


# --- Hybrid index ----------------------------------------------------------------------


def test_search_fuses_both_retrievers() -> None:
    index = rag.ContextIndex(CHUNKS, FakeEmbedder())
    results = index.search("faturamento por país", 2)
    assert results[0]["id"] == "example:revenue"
    assert results[0]["lexical_rank"] == 1
    assert results[0]["vector_rank"] == 1
    assert results[0]["score"] == pytest.approx(2 / (rag.RRF_K + 1), abs=1e-6)
    assert set(results[0]) == {
        "id", "kind", "title", "text", "score", "lexical_rank", "vector_rank"
    }  # fmt: skip


def test_search_without_lexical_match_still_ranks_by_vector() -> None:
    index = rag.ContextIndex(CHUNKS, FakeEmbedder())
    results = index.search("zzz", 3)
    assert len(results) == 3
    assert all(result["lexical_rank"] is None for result in results)
    assert all(result["vector_rank"] is not None for result in results)


@pytest.mark.parametrize(("k", "expected"), [(0, 1), (2, 2), (50, 3)])
def test_result_count_is_clamped(k: int, expected: int) -> None:
    index = rag.ContextIndex(CHUNKS, FakeEmbedder())
    assert len(index.search("invoice", k)) == expected


def test_lazy_index_is_built_once() -> None:
    embedder = FakeEmbedder()
    lazy = rag.LazyContextIndex(lambda: embedder)
    assert lazy.get() is lazy.get()
    assert embedder.passage_calls == 1


def test_missing_model_is_reported_without_downloading(tmp_path: Path) -> None:
    with pytest.raises(rag.ModelNotAvailableError, match="download-model"):
        rag.FastEmbedder(tmp_path / "empty-cache")


def test_model_cache_lives_in_the_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    assert rag.model_cache_dir() == tmp_path.resolve() / "models"


# --- MCP tool and command line ------------------------------------------------------------


@pytest.mark.anyio
async def test_search_context_tool(db_path: Path) -> None:
    lazy = rag.LazyContextIndex(FakeEmbedder)
    async with Client(server.create_server(db_path, context_index=lazy)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert tools["search_context"].annotations is not None
        assert tools["search_context"].annotations.read_only_hint is True
        result = await client.call_tool(
            "search_context", {"question": "faturamento de cada país", "k": 3}
        )
    assert not result.is_error
    assert result.structured_content is not None
    passages = result.structured_content["passages"]
    assert len(passages) == 3
    assert passages[0]["id"] == "example:revenue-per-country"


@pytest.mark.anyio
async def test_search_context_reports_missing_model(db_path: Path) -> None:
    def missing() -> rag.Embedder:
        raise rag.ModelNotAvailableError("Run 'uv run sqlite-consulta download-model' first.")

    lazy = rag.LazyContextIndex(missing)
    async with Client(server.create_server(db_path, context_index=lazy)) as client:
        result = await client.call_tool("search_context", {"question": "vendas"})
    assert result.is_error
    assert "download-model" in str(result.content)


@pytest.mark.anyio
async def test_search_context_validates_arguments(db_path: Path) -> None:
    lazy = rag.LazyContextIndex(FakeEmbedder)
    async with Client(server.create_server(db_path, context_index=lazy)) as client:
        too_many = await client.call_tool("search_context", {"question": "x", "k": 11})
        too_long = await client.call_tool("search_context", {"question": "x" * 501})
    assert too_many.is_error
    assert too_long.is_error


def test_main_download_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(chinook.DATA_DIR_ENV, str(tmp_path))
    calls: list[bool] = []

    def fake_download() -> Path:
        calls.append(True)
        return tmp_path

    monkeypatch.setattr(rag, "download_model", fake_download)
    server.main(["download-model"])
    assert calls == [True]
