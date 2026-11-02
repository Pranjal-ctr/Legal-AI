from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.config import Environment


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_name: str
    version: str
    environment: Environment
    timestamp: datetime


Readiness = Literal["loading", "ready", "unavailable", "disabled", "on_demand"]


class ReadyResponse(BaseModel):
    """What works right now. ``on_demand``: models load on first use (warm-up is off)."""

    answers: Readiness
    speech_input: Readiness
    speech_output: Readiness
