"""Rerankers: score (query, passage) pairs jointly; slower than retrieval, far more precise."""

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import structlog

from app.providers.hf import Device, local_snapshot, prepare_cache, resolve_device

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = structlog.get_logger(__name__)

MAX_LENGTH = 1024  # query + passage tokens; our passages are <= ~700 tokens


class RerankerProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Relevance of each passage to ``query``, higher is better (same order as input)."""
        ...


class CrossEncoderReranker:
    """sentence-transformers CrossEncoder (default ``BAAI/bge-reranker-v2-m3``, multilingual).

    Scores pass through a sigmoid, so they fall in [0, 1].
    """

    def __init__(
        self, model_name: str, cache_dir: Path, device: Device = "auto", batch_size: int = 16
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._device = device
        self._batch_size = batch_size
        self._model: CrossEncoder | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> "CrossEncoder":
        with self._lock:
            if self._model is None:
                prepare_cache(self._cache_dir)
                from sentence_transformers import CrossEncoder

                device = resolve_device(self._device)
                logger.info("reranker_loading", model=self._model_name, device=device)
                model = CrossEncoder(
                    local_snapshot(self._model_name, self._cache_dir),
                    device=device,
                    max_length=MAX_LENGTH,
                )
                if device == "cuda":
                    model.model.half()
                self._model = model
                logger.info("reranker_loaded", model=self._model_name, device=device)
            return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        scores = self._load().predict(
            [(query, p) for p in passages],
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [float(s) for s in scores]
