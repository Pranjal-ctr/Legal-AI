"""Speech endpoints: speech → text (Phase 9) and text → speech (Phase 10)."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile, status

from app.core.deps import ASRDep, SettingsDep, TTSDep
from app.core.security import rate_limit
from app.providers.asr import ASRError, ASRUnavailableError
from app.providers.tts import TTSError, TTSUnavailableError
from app.schemas.chat import LanguageCode
from app.schemas.speech import SpeechRequest, TranscriptOut

router = APIRouter(tags=["speech"], dependencies=[Depends(rate_limit("speech"))])


@router.post("/asr", response_model=TranscriptOut)
async def transcribe(
    audio: UploadFile,
    asr: ASRDep,
    settings: SettingsDep,
    language: Annotated[LanguageCode | None, Form()] = None,
) -> TranscriptOut:
    """Transcribe a short recording (webm/opus, ogg, wav, mp3, m4a) in English, Hindi or Kannada.

    The language is detected among those three unless given. The transcript is meant to be
    shown to the user for checking before it is sent as a question.
    """
    limit = int(settings.asr_max_upload_mb * 1024 * 1024)
    data = await audio.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The recording is larger than {settings.asr_max_upload_mb:g} MB.",
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The recording is empty.")
    try:
        transcript = await asyncio.to_thread(asr.transcribe, data, language)
    except ASRError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except ASRUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return TranscriptOut(
        text=transcript.text,
        language=transcript.language,
        language_probability=round(transcript.language_probability, 4),
        duration_s=round(transcript.duration_s, 2),
        model=asr.model_name,
    )


@router.post(
    "/tts",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}, "description": "16-bit mono WAV"}},
)
async def speak(body: SpeechRequest, tts: TTSDep, settings: SettingsDep) -> Response:
    """Read text aloud (English, Hindi or Kannada). Citation markers are skipped; quoted
    English law text followed by its translation is read as the translation. Send long
    answers sentence by sentence so playback can start early."""
    if len(body.text) > settings.tts_max_chars:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Send at most {settings.tts_max_chars} characters per request.",
        )
    try:
        audio = await asyncio.to_thread(tts.synthesize, body.text, body.language)
    except TTSError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except TTSUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"}
    )
