from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "app.123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, environment="test", sessions_dir=tmp_path / "s", frontend_dist=dist
    )
    return TestClient(create_app(settings))


def test_serves_index_assets_and_spa_fallback(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        index = client.get("/")
        asset = client.get("/assets/app.123.js")
        route = client.get("/some/client/route")

    assert index.text == "<html>app</html>"
    assert index.headers["Cache-Control"] == "no-cache"
    assert index.headers["X-Frame-Options"] == "DENY"  # security headers apply to the UI too
    assert asset.text == "console.log(1)"
    assert "immutable" in asset.headers["Cache-Control"]
    assert route.text == "<html>app</html>"


def test_api_routes_win_and_unknown_api_paths_stay_404(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        missing = client.get("/api/v1/nope")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}


def test_no_files_outside_dist(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/..%2fsecret.txt")

    assert "nope" not in response.text


def test_missing_build_is_not_mounted(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, environment="test", sessions_dir=tmp_path, frontend_dist=tmp_path / "x"
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 404
