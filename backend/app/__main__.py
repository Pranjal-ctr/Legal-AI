"""Run the API server with settings taken from the environment: `python -m app`."""

from pathlib import Path

import uvicorn

from app.core.config import load_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        reload_dirs=[str(BACKEND_DIR)],
        # Logging is configured by the app itself (app.core.logging).
        log_config=None,
    )


if __name__ == "__main__":
    main()
