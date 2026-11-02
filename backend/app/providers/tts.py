"""Text-to-speech providers. Phase 10 ships Meta MMS-TTS (VITS) for English, Hindi and Kannada,
run on CPU (the GPU is full with the LLM). Models load lazily per language.

MMS-TTS weights are CC-BY-NC 4.0: fine for this research prototype, not for commercial use.
"""

import io
import threading
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol

import structlog

from app.nlp.language import Language
from app.nlp.speech_text import speech_clauses
from app.providers.hf import local_snapshot, prepare_cache

logger = structlog.get_logger(__name__)

MMS_MODELS: dict[Language, str] = {
    "en": "facebook/mms-tts-eng",
    "hi": "facebook/mms-tts-hin",
    "kn": "facebook/mms-tts-kan",
}
PAUSE_S = 0.25  # between clauses (the voices cannot read punctuation)


class TTSError(RuntimeError):
    """Nothing speakable in the text."""


class TTSUnavailableError(RuntimeError):
    """The speech stack is not installed or the model cannot be loaded."""


class TTSProvider(Protocol):
    def load(self, language: Language) -> None: ...

    def synthesize(self, text: str, language: Language) -> bytes:
        """WAV bytes (16-bit mono PCM) of ``text`` read in ``language``."""
        ...


def to_wav(samples: Any, rate: int) -> bytes:
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class MMSTTS:
    def __init__(self, cache_dir: Path, cpu_threads: int = 0, cache_size: int = 128) -> None:
        self._cache_dir = cache_dir
        self._cpu_threads = cpu_threads
        self._models: dict[Language, tuple[Any, Any]] = {}
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, Language], bytes] = OrderedDict()
        self._cache_size = cache_size

    def _load(self, language: Language) -> tuple[Any, Any]:
        if language not in self._models:
            try:
                import torch
                from transformers import AutoTokenizer, VitsModel
            except ImportError as exc:
                raise TTSUnavailableError(
                    "Speech output is not installed: uv sync --extra speech"
                ) from exc
            if self._cpu_threads:
                torch.set_num_threads(self._cpu_threads)
            prepare_cache(self._cache_dir)
            path = local_snapshot(MMS_MODELS[language], self._cache_dir)
            logger.info("tts_loading", language=language, model=MMS_MODELS[language])
            tokenizer = AutoTokenizer.from_pretrained(path)
            model = VitsModel.from_pretrained(path)
            model.eval()  # type: ignore[no-untyped-call]
            self._models[language] = (tokenizer, model)
        return self._models[language]

    def load(self, language: Language) -> None:
        with self._lock:
            self._load(language)

    def synthesize(self, text: str, language: Language) -> bytes:
        key = (text, language)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            clauses = speech_clauses(text, language)
            if not clauses:
                raise TTSError("There is nothing to read aloud in this text.")
            import numpy as np
            import torch

            tokenizer, model = self._load(language)
            rate = int(model.config.sampling_rate)
            pause = np.zeros(int(PAUSE_S * rate), dtype=np.float32)
            parts: list[Any] = []
            torch.manual_seed(0)  # VITS samples durations: same text → same audio
            with torch.inference_mode():
                for clause in clauses:
                    inputs = tokenizer(clause, return_tensors="pt")
                    if inputs["input_ids"].shape[1] <= 2:  # nothing the voice knows
                        continue
                    parts += [model(**inputs).waveform[0].numpy(), pause]
            if not parts:
                raise TTSError("There is nothing to read aloud in this text.")
            audio = to_wav(np.concatenate(parts[:-1]), rate)
            self._cache[key] = audio
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        logger.info("tts_synthesized", language=language, chars=len(text), clauses=len(clauses))
        return audio
