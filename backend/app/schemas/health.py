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
