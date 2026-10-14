import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def spa_client(monkeypatch, tmp_path):
    import app as server_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("SPA", encoding="utf-8")
    (dist / "app.js").write_text("STATIC", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    monkeypatch.setattr(server_app, "dist_dir", str(dist))
    app = FastAPI()
    app.add_api_route("/{full_path:path}", server_app.serve_spa, methods=["GET"])
    return TestClient(app)


@pytest.mark.parametrize("path", ["/..%2fsecret.txt", "/..%5csecret.txt", "/C:%5csecret.txt", "/%00", "/api/missing", "/health-missing"])
def test_spa_rejects_unsafe_paths(spa_client, path):
    response = spa_client.get(path)
    assert response.status_code == 404
    assert "SECRET" not in response.text


def test_spa_keeps_static_and_history_fallback(spa_client):
    assert spa_client.get("/app.js").text == "STATIC"
    assert spa_client.get("/").text == "SPA"
    assert spa_client.get("/projects/demo").text == "SPA"
