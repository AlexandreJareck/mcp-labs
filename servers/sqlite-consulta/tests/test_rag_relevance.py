"""Relevance of `search_context` with the real multilingual model.

The model is downloaded once (``sqlite-consulta download-model``) and cached. In
CI, ``SQLITE_CONSULTA_REQUIRE_MODEL=1`` turns a missing model into a failure, so
these tests never pass silently by being skipped.
"""

import os

import pytest
from sqlite_consulta import rag

QUESTIONS: list[tuple[str, str]] = [
    ("quanto cada país faturou?", "example:revenue-per-country"),
    ("quais artistas vendem mais?", "example:best-selling-artists"),
    ("qual estilo de música tem mais faixas?", "example:tracks-per-genre"),
    ("quem gerencia quem na empresa?", "example:employee-hierarchy"),
    ("lista de músicas que ninguém comprou", "example:unsold-tracks"),
    ("vendas por mês em 2010", "example:monthly-sales"),
    ("which customers spent the most?", "example:top-customers"),
    ("duração das faixas", "example:longest-tracks"),
    ("playlists e suas músicas", "table:Playlist"),
    ("e-mail dos clientes", "example:customer-contact-masked"),
    ("faturas de um cliente", "table:Invoice"),
    ("qual vendedor atende mais clientes?", "example:customers-per-rep"),
]


@pytest.fixture(scope="module")
def index() -> rag.ContextIndex:
    try:
        return rag.LazyContextIndex().get()
    except rag.ModelNotAvailableError:
        if os.environ.get("SQLITE_CONSULTA_REQUIRE_MODEL") == "1":
            raise
        pytest.skip("embedding model not downloaded (run sqlite-consulta download-model)")


@pytest.mark.parametrize(("question", "expected"), QUESTIONS)
def test_expected_passage_is_in_the_top_three(
    index: rag.ContextIndex, question: str, expected: str
) -> None:
    ids = [passage["id"] for passage in index.search(question, 3)]
    assert expected in ids, ids


def test_overall_top_one_accuracy(index: rag.ContextIndex) -> None:
    hits = sum(index.search(question, 1)[0]["id"] == expected for question, expected in QUESTIONS)
    assert hits / len(QUESTIONS) >= 0.6


def test_search_is_deterministic(index: rag.ContextIndex) -> None:
    question = "quanto cada país faturou?"
    assert index.search(question, 5) == index.search(question, 5)
