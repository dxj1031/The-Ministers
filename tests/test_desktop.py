"""Desktop launch: reuse the right server; keep secrets local and bind localhost."""
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import desktop_court as desktop


def main():
    runtime = ROOT / "data" / f"desktop-test-{uuid.uuid4().hex}.json"
    config = {"api_key": "test-only-google-key", "model": "gemini-3.5-flash-lite", "mode": "google"}
    resolved = {**config, "base_url": desktop.BASE_URL, "engine": "google"}
    process = Mock()
    process.poll.return_value = None
    try:
        with patch.object(desktop, "resolve_model", return_value=resolved), \
                patch.object(desktop, "RUNTIME", runtime), patch.object(desktop, "find_port", return_value=(8018, False)), \
                patch.object(desktop, "court_running", return_value=True), \
                patch.object(desktop.subprocess, "Popen", return_value=process) as spawn:
            url = desktop.launch(config)
            assert url == "http://127.0.0.1:8018/front/The%20Court.dc.html"
            args, kwargs = spawn.call_args
            assert args[0][-3:] == ["127.0.0.1", "--port", "8018"]
            assert kwargs["env"]["MINISTERS_API_KEY"] == config["api_key"]
            assert kwargs["env"]["MINISTERS_BASE_URL"].startswith("https://generativelanguage.googleapis.com/")
            assert not kwargs["env"]["MINISTERS_ACCESS_KEY"] and "RENDER" not in kwargs["env"]
            assert kwargs["env"]["MINISTERS_DB"] == str(ROOT / "data" / "ministers.db")
            assert config["api_key"] not in runtime.read_text()
            if os.name == "nt":
                assert kwargs["creationflags"] == desktop.subprocess.CREATE_NO_WINDOW
        with patch.object(desktop, "court_running", return_value=True):
            assert desktop.find_port("correct", {"8019": "correct"}) == (8019, True)
        with patch.object(desktop, "resolve_model", return_value=resolved), \
                patch.object(desktop, "RUNTIME", runtime), patch.object(desktop, "find_port", return_value=(8018, True)), \
                patch.object(desktop.subprocess, "Popen") as spawn:
            desktop.launch(config)
            spawn.assert_not_called()
        with patch.object(desktop, "gpu_5060", return_value={"name": "RTX 5060 Ti", "memory": 16000}), \
                patch.object(desktop, "local_model", return_value={"engine": "local"}) as local:
            assert desktop.resolve_model({"mode": "auto"})["engine"] == "local"
            local.assert_called_once()
        with patch.object(desktop, "gpu_5060", return_value=None):
            assert desktop.resolve_model({**config, "mode": "auto"})["engine"] == "google"
        replies = [{"models": [{"name": "qwen2.5:14b"}]}, {}, {"models": [{"name": "qwen2.5:14b", "size_vram": 8000000000}]}]
        with patch.object(desktop, "ollama_json", side_effect=replies):
            local = desktop.local_model({"memory": 16000}, {})
            assert local["engine"] == "local" and local["api_key"] == "ollama"
        replies[-1] = {"models": [{"name": "qwen2.5:14b", "size_vram": 0}]}
        with patch.object(desktop, "ollama_json", side_effect=replies):
            try:
                desktop.local_model({"memory": 16000}, {})
                raise AssertionError("A detected card alone does not prove GPU inference")
            except RuntimeError as exc:
                assert "显存" in str(exc)
        print("desktop OK: hidden localhost server, cloud credentials kept out of URL/runtime metadata, matching instance reused")
    finally:
        runtime.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
