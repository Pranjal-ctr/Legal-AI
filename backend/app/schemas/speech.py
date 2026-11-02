from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.chat import LanguageCode


class TranscriptOut(BaseModel):
    text: str = Field(description="Show to the user for checking before sending it as a question.")
    language: LanguageCode
    language_probability: float = Field(description="1.0 when the language was given.")
    duration_s: float
    model: str


class SpeechRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    language: LanguageCode
