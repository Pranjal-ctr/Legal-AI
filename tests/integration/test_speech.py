from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.deps import get_asr, get_tts
from app.main import create_app
from app.providers.asr import ASRError
from app.providers.tts import TTSError
from tests.fakes import FakeASR, FakeTTS


def _client(
    asr: FakeASR, tmp_path: Path, tts: FakeTTS | None = None, **overrides: object
) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, environment="test", sessions_dir=tmp_path / "s", **overrides
    )
    app = create_app(settings)
    app.dependency_overrides[get_asr] = lambda: asr
    app.dependency_overrides[get_tts] = lambda: tts or FakeTTS()
    return TestClient(app)


def test_asr_returns_transcript(tmp_path: Path) -> None:
    asr = FakeASR("क्या मैं तलाक ले सकती हूँ?")
    with _client(asr, tmp_path) as client:
        response = client.post(
            "/api/v1/asr",
            files={"audio": ("q.webm", b"\x1a\x45\xdf\xa3 fake", "audio/webm")},
            data={"language": "hi"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "text": "क्या मैं तलाक ले सकती हूँ?",
        "language": "hi",
        "language_probability": 1.0,
        "duration_s": 2.5,
        "model": "fake-asr",
    }
    assert asr.calls == [(len(b"\x1a\x45\xdf\xa3 fake"), "hi")]


def test_asr_detects_language_when_not_given(tmp_path: Path) -> None:
    asr = FakeASR()
    with _client(asr, tmp_path) as client:
        body = client.post("/api/v1/asr", files={"audio": ("q.wav", b"RIFF", "audio/wav")}).json()

    assert asr.calls[0][1] is None
    assert body["language"] == "en"


def test_asr_rejects_large_empty_and_undecodable_uploads(tmp_path: Path) -> None:
    with _client(FakeASR(), tmp_path, asr_max_upload_mb=0.001) as client:
        big = client.post("/api/v1/asr", files={"audio": ("q.wav", b"x" * 2000, "audio/wav")})
        empty = client.post("/api/v1/asr", files={"audio": ("q.wav", b"", "audio/wav")})
        bad_lang = client.post(
            "/api/v1/asr", files={"audio": ("q.wav", b"x", "audio/wav")}, data={"language": "fr"}
        )
    assert big.status_code == 413
    assert empty.status_code == 422
    assert bad_lang.status_code == 422

    with _client(FakeASR(error=ASRError("The audio could not be decoded.")), tmp_path) as client:
        bad = client.post("/api/v1/asr", files={"audio": ("q.wav", b"xyz", "audio/wav")})
    assert bad.status_code == 422
    assert bad.json()["detail"] == "The audio could not be decoded."


def test_asr_disabled_answers_503(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, environment="test", sessions_dir=tmp_path / "s", asr_enabled=False
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/asr", files={"audio": ("q.wav", b"x", "audio/wav")})

    assert response.status_code == 503


def test_tts_returns_wav(tmp_path: Path) -> None:
    tts = FakeTTS()
    with _client(FakeASR(), tmp_path, tts) as client:
        response = client.post("/api/v1/tts", json={"text": " तलाक [1]। ", "language": "hi"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content.startswith(b"RIFF")
    assert tts.calls == [("तलाक [1]।", "hi")]


def test_tts_validates_input(tmp_path: Path) -> None:
    with _client(FakeASR(), tmp_path, FakeTTS(), tts_max_chars=50) as client:
        too_long = client.post("/api/v1/tts", json={"text": "a" * 51, "language": "en"})
        bad_lang = client.post("/api/v1/tts", json={"text": "hello", "language": "fr"})
    assert too_long.status_code == 413
    assert bad_lang.status_code == 422

    with _client(FakeASR(), tmp_path, FakeTTS(error=TTSError("nothing to read"))) as client:
        nothing = client.post("/api/v1/tts", json={"text": "[1]", "language": "en"})
    assert nothing.status_code == 422
