"""FastAPI dependencies shared across routers."""

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.config import Settings


def get_settings(request: Request) -> Settings:
    """Settings live on the app instance (no module globals), so tests can inject their own."""
    return cast(Settings, request.app.state.settings)


SettingsDep = Annotated[Settings, Depends(get_settings)]
