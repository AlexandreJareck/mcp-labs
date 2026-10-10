"""Hybrid retrieval (lexical + vector) over the data dictionary and example queries.

Everything runs locally: BM25 is implemented here, and the embeddings come from a
small multilingual model run by `fastembed` (ONNX), downloaded once with
``sqlite-consulta download-model`` (ADR-0008, ADR-0014). The index is rebuilt in
memory from the versioned files; nothing derived is stored.
"""

import json
import logging
import math
import re
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast

import numpy as np
import numpy.typing as npt

from sqlite_consulta import chinook, dictionary

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EXAMPLES_FILE = "examples.json"
RRF_K = 60
MAX_RESULTS = 10

type Vector = npt.NDArray[np.float32]
type ChunkKind = Literal["table", "example"]

# Words that carry no meaning for retrieval, in Portuguese and English.
STOPWORDS = frozenset(
    [
        "a",
        "o",
        "as",
        "os",
        "um",
        "uma",
        "uns",
        "umas",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "no",
        "na",
        "nos",
        "nas",
        "em",
        "por",
        "para",
        "com",
        "sem",
        "que",
        "qual",
        "quais",
        "quem",
        "como",
        "e",
        "ou",
        "se",
        "ao",
        "aos",
        "cada",
        "mais",
        "menos",
        "ja",
        "foi",
        "foram",
        "ser",
        "sao",
        "tem",
        "ha",
        "existem",
        "the",
        "of",
        "and",
        "or",
        "to",
        "in",
        "on",
        "for",
        "by",
        "with",
        "is",
        "are",
        "was",
        "were",
        "which",
        "what",
        "who",
        "how",
        "each",
        "per",
        "from",
    ]
)


class Embedder(Protocol):
    """Turns text into vectors; implemented by `FastEmbedder` and by test fakes."""

    def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        """Embed passages to be searched."""
        ...

    def embed_query(self, text: str) -> Vector:
        """Embed a search query."""
        ...


class ModelNotAvailableError(RuntimeError):
    """The embedding model is not in the local cache."""


def model_cache_dir() -> Path:
    """Return where the embedding model is stored: ``models/`` in the data directory."""
    return chinook.data_dir() / "models"


class FastEmbedder:
    """`fastembed` model that only reads the local cache (never downloads at query time)."""

    def __init__(self, cache_dir: Path | None = None, *, allow_download: bool = False) -> None:
        """Load the model.

        Args:
            cache_dir: Model cache directory; defaults to `model_cache_dir()`.
            allow_download: Download the model when it is missing (used only by
                ``download-model``).

        Raises:
            ModelNotAvailableError: If the model is not cached and downloads are off.
        """
        from fastembed import TextEmbedding

        cache = cache_dir or model_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        try:
            self._model = TextEmbedding(
                MODEL_NAME, cache_dir=str(cache), local_files_only=not allow_download
            )
        except Exception as error:  # fastembed raises several types when files are missing
            if allow_download:
                raise
            logger.warning("Could not load the embedding model: %s", error)
            raise ModelNotAvailableError(
                "Embedding model not found. Run 'uv run sqlite-consulta download-model' first."
            ) from error

    def embed_passages(self, texts: Sequence[str]) -> list[Vector]:
        """Embed passages to be searched."""
        return [np.asarray(vector, dtype=np.float32) for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> Vector:
        """Embed a search query."""
        (vector,) = list(self._model.query_embed([text]))
        return np.asarray(vector, dtype=np.float32)


def download_model(cache_dir: Path | None = None) -> Path:
    """Download the embedding model from its public Hugging Face repository.

    Args:
        cache_dir: Model cache directory; defaults to `model_cache_dir()`.

    Returns:
        The cache directory.
    """
    cache = cache_dir or model_cache_dir()
    FastEmbedder(cache, allow_download=True)
    logger.info("Embedding model %s is available in %s", MODEL_NAME, cache)
    return cache


# --- Chunks -------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """A searchable passage.

    Attributes:
        id: Stable identifier, such as ``table:Track`` or ``example:revenue-per-country``.
        kind: ``table`` (a data dictionary entry) or ``example`` (a question with SQL).
        title: Short label.
        text: The passage returned to the client.
    """

    id: str
    kind: ChunkKind
    title: str
    text: str


class _Example(TypedDict):
    id: str
    question: str
    sql: str


def load_examples() -> list[_Example]:
    """Read the versioned example questions shipped inside the package.

    Returns:
        The examples, each with an id, a question, and its SQL.
    """
    text = resources.files("sqlite_consulta").joinpath(EXAMPLES_FILE).read_text("utf-8")
    return cast("list[_Example]", json.loads(text))


def build_chunks() -> list[Chunk]:
    """Split the data dictionary and the examples into passages.

    One passage per table (its description and every column) and one per
    example (the question and its SQL), so each passage answers one need.

    Returns:
        The passages, in a stable order.
    """
    source = dictionary.load_source()
    chunks: list[Chunk] = []
    for name, table in source["tables"].items():
        columns = "\n".join(f"- {column}: {text}" for column, text in table["columns"].items())
        chunks.append(
            Chunk(
                id=f"table:{name}",
                kind="table",
                title=f"Table {name}",
                text=f"Table {name}: {table['description']}\nColumns:\n{columns}",
            )
        )
    for example in load_examples():
        chunks.append(
            Chunk(
                id=f"example:{example['id']}",
                kind="example",
                title=example["question"],
                text=f"Question: {example['question']}\nSQL: {example['sql']}",
            )
        )
    return chunks


# --- Lexical search (BM25) --------------------------------------------------------

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Normalize text into search terms.

    Splits camelCase (``InvoiceLine`` becomes ``invoice line``), removes accents,
    lowercases, and drops stopwords and one-letter terms.

    Args:
        text: Any text.

    Returns:
        The terms, in order.
    """
    spaced = _CAMEL.sub(" ", text)
    plain = unicodedata.normalize("NFKD", spaced).encode("ascii", "ignore").decode()
    return [
        token
        for token in _TOKEN.findall(plain.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


class BM25:
    """Okapi BM25 over a fixed set of documents."""

    def __init__(self, documents: Iterable[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        """Index the documents.

        Args:
            documents: Tokenized documents.
            k1: Term frequency saturation.
            b: Length normalization.
        """
        self._docs = [Counter(tokens) for tokens in documents]
        self._lengths = [sum(doc.values()) for doc in self._docs]
        self._avg = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        frequencies: Counter[str] = Counter()
        for doc in self._docs:
            frequencies.update(doc.keys())
        total = len(self._docs)
        self._idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for term, count in frequencies.items()
        }
        self._k1 = k1
        self._b = b

    def scores(self, query: list[str]) -> list[float]:
        """Score every document for a tokenized query.

        Args:
            query: Query terms.

        Returns:
            One score per document; zero when no term matches.
        """
        result: list[float] = []
        for doc, length in zip(self._docs, self._lengths, strict=True):
            score = 0.0
            for term in set(query):
                frequency = doc.get(term, 0)
                if frequency:
                    norm = self._k1 * (1 - self._b + self._b * length / (self._avg or 1))
                    score += self._idf[term] * frequency * (self._k1 + 1) / (frequency + norm)
            result.append(score)
        return result


# --- Hybrid search ---------------------------------------------------------------


class Passage(TypedDict):
    """A retrieved passage with how each retriever ranked it."""

    id: str
    kind: ChunkKind
    title: str
    text: str
    score: float
    lexical_rank: int | None
    vector_rank: int | None


def _ranks(scores: Sequence[float], *, require_positive: bool) -> dict[int, int]:
    order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
    if require_positive:
        order = [index for index in order if scores[index] > 0]
    return {index: rank for rank, index in enumerate(order, start=1)}


class ContextIndex:
    """In-memory hybrid index, fused with Reciprocal Rank Fusion."""

    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder) -> None:
        """Build the lexical and vector indexes.

        Args:
            chunks: The passages to index.
            embedder: Embedding model.
        """
        self._chunks = list(chunks)
        self._embedder = embedder
        self._bm25 = BM25(tokenize(f"{chunk.title} {chunk.text}") for chunk in self._chunks)
        vectors = np.vstack(embedder.embed_passages([chunk.text for chunk in self._chunks]))
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        self._vectors = vectors / np.where(norms == 0, 1, norms)

    def search(self, question: str, k: int = 5) -> list[Passage]:
        """Return the passages most relevant to a question.

        Each retriever ranks the passages; the final score is the sum of
        ``1 / (RRF_K + rank)`` over the retrievers that ranked the passage.

        Args:
            question: Natural-language question, in any supported language.
            k: Number of passages to return (1 to `MAX_RESULTS`).

        Returns:
            The best passages, best first.
        """
        k = max(1, min(k, MAX_RESULTS))
        lexical = _ranks(self._bm25.scores(tokenize(question)), require_positive=True)
        query = self._embedder.embed_query(question)
        norm = float(np.linalg.norm(query)) or 1.0
        similarities = (self._vectors @ (query / norm)).tolist()
        vector = _ranks(similarities, require_positive=False)
        fused = {
            index: sum(1 / (RRF_K + ranks[index]) for ranks in (lexical, vector) if index in ranks)
            for index in range(len(self._chunks))
        }
        best = sorted(fused, key=lambda index: (-fused[index], self._chunks[index].id))[:k]
        return [
            Passage(
                id=self._chunks[index].id,
                kind=self._chunks[index].kind,
                title=self._chunks[index].title,
                text=self._chunks[index].text,
                score=round(fused[index], 6),
                lexical_rank=lexical.get(index),
                vector_rank=vector.get(index),
            )
            for index in best
        ]


class LazyContextIndex:
    """Builds the index on first use, once, from the versioned files."""

    def __init__(self, embedder_factory: Callable[[], Embedder] | None = None) -> None:
        """Remember how to create the embedder.

        Args:
            embedder_factory: Callable that returns an `Embedder`; defaults to `FastEmbedder`.
        """
        self._factory: Callable[[], Embedder] = embedder_factory or FastEmbedder
        self._index: ContextIndex | None = None
        self._lock = threading.Lock()

    def get(self) -> ContextIndex:
        """Return the index, building it on the first call.

        Raises:
            ModelNotAvailableError: If the embedding model is not cached.
        """
        with self._lock:
            if self._index is None:
                self._index = ContextIndex(build_chunks(), self._factory())
            return self._index
