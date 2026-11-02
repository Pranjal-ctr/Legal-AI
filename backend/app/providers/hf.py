"""Shared helpers for locally cached Hugging Face models (embedder, reranker, TTS)."""

import os
from pathlib import Path
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

Device = Literal["auto", "cpu", "cuda"]

# Repo files our loaders never read (several BAAI repos ship multi-GB ONNX exports).
SKIP_FILES = ["onnx/*", "*.onnx", "*.onnx_data", "imgs/*", "assets/*"]


def prepare_cache(cache_dir: Path) -> None:
    """Keep every Hugging Face cache on the project drive (never the user profile)."""
    os.environ.setdefault("HF_HOME", str(cache_dir.resolve()))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows without dev mode


def resolve_device(device: Device) -> str:
    if device != "auto":
        return device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def local_snapshot(repo_id: str, cache_dir: Path) -> str:
    """Local snapshot dir of ``repo_id``, downloading it once if needed.

    Loading from a path (not a repo id) keeps start-up offline: transformers otherwise
    queries the Hub on every load (e.g. its safetensors auto-conversion check).
    """
    if Path(repo_id).is_dir():
        return repo_id
    prepare_cache(cache_dir)
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(
            repo_id,
            cache_dir=cache_dir,
            ignore_patterns=SKIP_FILES,  # else the skipped files count as "incomplete"
            local_files_only=True,
        )
    except Exception:  # not cached yet (huggingface_hub raises several error types)
        logger.info("hf_model_downloading", model=repo_id)
        return snapshot_download(repo_id, cache_dir=cache_dir, ignore_patterns=SKIP_FILES)
