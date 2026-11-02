"""Embedding providers: text → L2-normalised dense vectors (cosine similarity = dot product)."""

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import structlog

from app.providers.hf import Device, local_snapshot, prepare_cache, resolve_device

if TYPE_CHECKING:  # heavy import (torch); only needed at runtime by the real provider
    from sentence_transformers import SentenceTransformer

logger = structlog.get_logger(__name__)

# bge-m3 accepts 8192 tokens; our longest retrieval unit is ~2.4k characters (~700 tokens),
# so 1024 keeps every chunk whole while bounding GPU memory next to the local LLM.
MAX_SEQ_LENGTH = 1024


class EmbeddingProvider(Protocol):
    """Embeds documents (index time) and queries (request time) into the same vector space."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Local sentence-transformers model (default ``BAAI/bge-m3``, dense head only).

    bge-m3 needs no query instruction prefix, so queries and documents are encoded identically.
    Weights download once into ``cache_dir``; the model loads lazily on first use.
    """

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        device: Device = "auto",
        batch_size: int = 16,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._device = device
        self._batch_size = batch_size
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        dim = self._load().get_embedding_dimension()
        if dim is None:  # pragma: no cover - every bge/e5-style model reports one
            raise RuntimeError(f"{self._model_name} does not report an embedding dimension")
        return int(dim)

    def _load(self) -> "SentenceTransformer":
        with self._lock:
            if self._model is None:
                prepare_cache(self._cache_dir)
                from sentence_transformers import SentenceTransformer

                device = resolve_device(self._device)
                logger.info("embedding_model_loading", model=self._model_name, device=device)
                path = local_snapshot(self._model_name, self._cache_dir)
                model = SentenceTransformer(path, device=device)
                if device == "cuda":
                    model.half()  # halves VRAM (~1.1 GB for bge-m3); negligible quality change
                model.max_seq_length = MAX_SEQ_LENGTH
                self._model = model
                logger.info("embedding_model_loaded", model=self._model_name, device=device)
            return self._model

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._load().encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in row] for row in vectors]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]
