"""Hosted access must protect both model actions and stored private records."""
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / f"deploy-test-{uuid.uuid4().hex}.db"
os.environ["MINISTERS_DB"] = str(DB)

from fastapi.testclient import TestClient
from app.back.main import app
from app.back.core import access, llm


def main():
    env = {"RENDER": "true", "MINISTERS_ACCESS_KEY": "test-only-court-password"}
    with patch.dict(os.environ, env), patch.object(llm, "API_KEY", "test-only-model-key"), \
            patch.object(llm, "BASE_URL", "https://model.example/v1"):
        with TestClient(app, base_url="https://court.example") as client:
            assert client.get("/api/health").json() == {"ok": True}
            assert client.get("/front/The%20Court.dc.html").status_code == 200
            for route in ("/api/sessions", "/api/traces", "/api/stats", "/api/court/private", "/api/evals"):
                assert client.get(route).status_code == 401, route
            with patch("app.back.main.court.open_court") as model_action:
                assert client.post("/api/court", json={"topic": "test"}).status_code == 401
                model_action.assert_not_called()
            assert client.post("/api/access", json={"password": "wrong"}).status_code == 401
            login = client.post("/api/access", json={"password": env["MINISTERS_ACCESS_KEY"]})
            assert login.status_code == 200
            cookie = login.headers["set-cookie"].lower()
            assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
            data = client.get("/api/sessions")
            assert data.status_code == 200 and data.headers["cache-control"] == "no-store"
            with patch("app.back.main.court.open_court", return_value={"id": "authorized"}) as model_action:
                assert client.post("/api/court", json={"topic": "test"}).json()["id"] == "authorized"
                model_action.assert_called_once()
            client.cookies.clear()
            client.cookies.set(access.COOKIE, "12345.tampered")
            assert client.get("/api/sessions").status_code == 401
            with patch.object(access.time, "time", return_value=time.time() - access.MAX_AGE - 10):
                expired = access.issue()
            client.cookies.set(access.COOKIE, expired)
            assert client.get("/api/sessions").status_code == 401
            access._attempts.clear()
            for _ in range(6):
                assert client.post("/api/access", json={"password": "wrong"}).status_code == 401
            assert client.post("/api/access", json={"password": "wrong"}).status_code == 429
        with patch.dict(os.environ, {"MINISTERS_ACCESS_KEY": ""}):
            try:
                with TestClient(app):
                    raise AssertionError("An unprotected hosted court must not start")
            except RuntimeError as exc:
                assert "MINISTERS_ACCESS_KEY" in str(exc)
        with patch.object(llm, "BASE_URL", "http://127.0.0.1:11434/v1"):
            try:
                with TestClient(app):
                    raise AssertionError("Cloud deployments cannot silently use localhost models")
            except RuntimeError as exc:
                assert "HTTPS" in str(exc)
    print("deployment OK: hosted startup validation, blocked records/model calls, secure login, tampering, expiry and retry limits")


if __name__ == "__main__":
    try:
        main()
    finally:
        DB.unlink(missing_ok=True)
