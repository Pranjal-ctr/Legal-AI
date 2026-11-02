"""Speech recognition providers. Phase 9 ships faster-whisper (CTranslate2), CPU int8 by default
because the GPU is shared by the embedder, reranker and LLM.

Language is detected among the supported languages only (en / hi / kn), unless given.
Heavy imports happen on first use, so the API starts (and tests run) without the `speech` extra.
"""

import io
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, get_args

import structlog

from app.nlp.language import Language

logger = structlog.get_logger(__name__)

SAMPLE_RATE = 16_000
NOT_INSTALLED = "Speech recognition is not installed: uv sync --extra speech"
SUPPORTED: tuple[Language, ...] = get_args(Language)


class ASRError(RuntimeError):
    """The audio cannot be transcribed (undecodable, empty, too long)."""


class ASRUnavailableError(RuntimeError):
    """The speech stack is not installed or the model cannot be loaded."""


@dataclass(frozen=True)
class Transcript:
    text: str
    language: Language
    language_probability: float  # 1.0 when the language was given
    duration_s: float


class ASRProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    def load(self) -> None:
        """Load the model now (startup warm-up) instead of on the first request."""
        ...

    def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        """Transcribe an audio file (any format PyAV/FFmpeg decodes: webm/opus, wav, mp3, ...)."""
        ...


AMBIGUOUS_BELOW = 0.8  # renormalised probability under which the runner-up is also decoded


def rank_languages(probabilities: list[tuple[str, float]]) -> list[tuple[Language, float]]:
    """Supported languages by probability, renormalised over the supported ones."""
    supported = [(lang, p) for lang, p in probabilities if lang in SUPPORTED]
    if not supported:
        return [("en", 0.0)]
    total = sum(p for _, p in supported) or 1.0
    ranked = sorted(supported, key=lambda item: item[1], reverse=True)
    return [(lang, p / total) for lang, p in ranked]


def pick_language(probabilities: list[tuple[str, float]]) -> tuple[Language, float]:
    """The most probable supported language, renormalised over the supported ones."""
    return rank_languages(probabilities)[0]


def decode_audio(audio: bytes, max_seconds: float = 120.0) -> Any:
    """Decode any container PyAV reads into 16 kHz mono float32 samples (numpy array).

    Our own decoder: faster-whisper 1.2's helper passes an argument PyAV >= 15 removed.
    Decoding stops after ``max_seconds`` so a huge upload cannot exhaust memory.
    """
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise ASRUnavailableError(NOT_INSTALLED) from exc

    chunks: list[Any] = []
    total = 0
    limit = int(max_seconds * SAMPLE_RATE)
    try:
        with av.open(io.BytesIO(audio), mode="r") as container:
            if not container.streams.audio:
                raise ASRError("The file contains no audio.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunk = out.to_ndarray().reshape(-1)
                    chunks.append(chunk)
                    total += len(chunk)
                if total > limit:
                    break
            for out in resampler.resample(None):  # flush
                chunks.append(out.to_ndarray().reshape(-1))
    except ASRError:
        raise
    except Exception as exc:  # PyAV raises several error types for bad input
        raise ASRError("The audio could not be decoded.") from exc
    if not chunks:
        raise ASRError("The recording is empty.")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


WINDOW_SECONDS = 30  # Whisper's fixed encoder window


def _speech_only(samples: Any) -> Any:
    """Silero VAD (bundled with faster-whisper): keep speech, drop silence. Silence is where
    Whisper hallucinates words ("Thank you for watching")."""
    import numpy as np
    from faster_whisper.vad import get_speech_timestamps

    spans = get_speech_timestamps(samples)
    if not spans:
        return samples[:0]
    return np.concatenate([samples[s["start"] : s["end"]] for s in spans])


class FasterWhisperASR:
    def __init__(
        self,
        model: str,
        cache_dir: Path,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        beam_size: int = 1,
        max_seconds: float = 60.0,
    ) -> None:
        self._model_name = model
        self._cache_dir = cache_dir
        self._device = device
        self._compute_type = compute_type
        self._cpu_threads = cpu_threads
        self._beam_size = beam_size
        self._max_seconds = max_seconds
        self._model: Any = None
        self._lock = threading.Lock()  # one transcription at a time: CPU-bound

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ASRUnavailableError(NOT_INSTALLED) from exc
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("asr_loading", model=self._model_name, device=self._device)
            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
                cpu_threads=self._cpu_threads,
                download_root=str(self._cache_dir),
            )
        return self._model

    def load(self) -> None:
        with self._lock:
            self._load()

    def _single_window(
        self, model: Any, speech: Any, language: Language | None
    ) -> tuple[str, Language, float]:
        """Up to 30 s: ONE encoder pass serves both language detection (restricted to the
        supported languages) and decoding. ``WhisperModel.transcribe`` encodes twice when the
        language is unknown, which costs ~8 s extra on CPU."""
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.tokenizer import Tokenizer
        from faster_whisper.transcribe import get_suppressed_tokens

        features = pad_or_trim(model.feature_extractor(speech))
        encoded = model.encode(features)

        def decode(lang: Language) -> tuple[str, float]:
            tokenizer = Tokenizer(model.hf_tokenizer, True, task="transcribe", language=lang)
            result = model.model.generate(
                encoded,
                [model.get_prompt(tokenizer, [], without_timestamps=True)],
                beam_size=self._beam_size,
                max_length=model.max_length,
                suppress_blank=True,
                suppress_tokens=list(get_suppressed_tokens(tokenizer, (-1,)) or ()),
                return_scores=True,
            )[0]
            # score = length-normalised log-probability of the transcript
            return tokenizer.decode(result.sequences_ids[0]).strip(), float(result.scores[0])

        if language is not None:
            return decode(language)[0], language, 1.0
        ranked = model.model.detect_language(encoded)[0]  # [(token "<|hi|>", prob), ...]
        candidates = rank_languages([(tok[2:-2], p) for tok, p in ranked])
        best, probability = candidates[0]
        text, score = decode(best)
        if probability < AMBIGUOUS_BELOW and len(candidates) > 1:
            # Unsure (Whisper often scores Kannada speech as Hindi): decode the runner-up from
            # the same encoder output and keep the transcript the model finds more probable.
            other, other_probability = candidates[1]
            other_text, other_score = decode(other)
            logger.info(
                "asr_ambiguous",
                first=(best, round(score, 3)),
                second=(other, round(other_score, 3)),
            )
            if other_score > score:
                return other_text, other, other_probability
        return text, best, probability

    def transcribe(self, audio: bytes, language: Language | None = None) -> Transcript:
        with self._lock:
            model = self._load()
            samples = decode_audio(audio, max_seconds=self._max_seconds + 1)
            duration = len(samples) / SAMPLE_RATE
            if duration < 0.3:
                raise ASRError("The recording is empty or too short.")
            if duration > self._max_seconds:
                raise ASRError(f"The recording is longer than {self._max_seconds:.0f} seconds.")

            speech = _speech_only(samples)
            if len(speech) < 0.3 * SAMPLE_RATE:
                raise ASRError("No speech was detected in the recording.")
            if len(speech) <= WINDOW_SECONDS * SAMPLE_RATE:
                text, language, probability = self._single_window(model, speech, language)
            else:
                probability = 1.0
                if language is None:
                    _, _, all_probs = model.detect_language(speech)
                    language, probability = pick_language(all_probs)
                segments, _ = model.transcribe(
                    speech,
                    language=language,
                    beam_size=self._beam_size,
                    condition_on_previous_text=False,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
        logger.info(
            "asr_transcribed",
            language=language,
            probability=round(probability, 3),
            seconds=round(duration, 1),
            chars=len(text),
        )
        return Transcript(text, language, probability, duration)
