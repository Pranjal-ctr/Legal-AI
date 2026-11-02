import io
import math
import struct
import wave

import pytest

from app.providers.asr import ASRError, decode_audio, pick_language, rank_languages


def test_pick_language_restricts_to_supported_languages() -> None:
    # Hindi speech is often scored as Urdu; only en/hi/kn may be chosen.
    probs = [("ur", 0.6), ("hi", 0.3), ("en", 0.1), ("ta", 0.05)]

    language, probability = pick_language(probs)

    assert language == "hi"
    assert probability == pytest.approx(0.75)


def test_pick_language_defaults_to_english_without_candidates() -> None:
    assert pick_language([("fr", 1.0)]) == ("en", 0.0)


def _wav(seconds: float, rate: int = 44_100) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<hh", v, v)
            for v in (
                int(8000 * math.sin(2 * math.pi * 440 * n / rate))
                for n in range(int(seconds * rate))
            )
        )
        w.writeframes(frames)
    return buf.getvalue()


def test_decode_audio_resamples_to_16k_mono_float() -> None:
    pytest.importorskip("av")

    samples = decode_audio(_wav(1.0))

    assert samples.dtype.name == "float32"
    assert abs(len(samples) - 16_000) < 400
    assert float(abs(samples).max()) <= 1.0


def test_decode_audio_stops_at_the_limit() -> None:
    pytest.importorskip("av")

    samples = decode_audio(_wav(3.0), max_seconds=1.0)

    assert len(samples) < 2 * 16_000


def test_decode_audio_rejects_garbage() -> None:
    pytest.importorskip("av")

    with pytest.raises(ASRError):
        decode_audio(b"definitely not audio")


def test_rank_languages_orders_supported_languages() -> None:
    ranked = rank_languages([("hi", 0.5), ("kn", 0.3), ("ta", 0.15), ("en", 0.05)])

    assert [lang for lang, _ in ranked] == ["hi", "kn", "en"]
    assert ranked[0][1] == pytest.approx(0.5 / 0.85)
