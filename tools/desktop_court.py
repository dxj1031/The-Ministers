"""Windows desktop entry: first-run Google AI setup, hidden API, then browser."""
import json
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SETTINGS = DATA / "desktop-google.json"  # data/ is ignored by Git.
RUNTIME = DATA / "desktop-runtime.json"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MODEL = "gemini-3.5-flash-lite"


def settings() -> dict:
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def court_running(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            if not json.load(response).get("ok"):
                return False
        with urlopen(f"http://127.0.0.1:{port}/front/The%20Court.dc.html", timeout=2) as response:
            return b'ministers-app' in response.read()
    except (URLError, OSError, ValueError):
        return False


def find_port(fingerprint: str, known: dict) -> tuple[int, bool]:
    for port in range(8018, 8023):
        if known.get(str(port)) == fingerprint and court_running(port):
            return port, True
    for port in range(8018, 8023):
        if court_running(port):
            continue
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port, False
            except OSError:
                continue
    raise RuntimeError("本地已有多个服务运行，请重启电脑后再试。")


def launch(config: dict) -> str:
    fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    try:
        known = json.loads(RUNTIME.read_text(encoding="utf-8"))
        if not isinstance(known, dict):
            known = {}
    except (OSError, ValueError):
        known = {}
    port, running = find_port(fingerprint, known)
    if not running:
        env = os.environ.copy()
        env.update(MINISTERS_BASE_URL=BASE_URL, MINISTERS_API_KEY=config["api_key"],
                   MINISTERS_MODEL=config.get("model") or MODEL, MINISTERS_TIMEOUT="180",
                   MINISTERS_DB=str(DATA / "ministers.db"))
        # Cloud-only settings must not turn the private localhost app into a hosted service.
        env.pop("RENDER", None)
        env["MINISTERS_ACCESS_KEY"] = ""
        python = Path(sys.executable).with_name("python.exe") if os.name == "nt" else Path(sys.executable)
        DATA.mkdir(exist_ok=True)
        with (DATA / "desktop-api.log").open("ab") as log:
            process = subprocess.Popen(
                [str(python), "-m", "uvicorn", "app.back.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("朝堂服务启动失败，请查看 data/desktop-api.log。若缺少依赖，请先安装 requirements.txt。")
            if court_running(port):
                break
            time.sleep(1)
        else:
            process.terminate()  # Only the child created by this launch.
            raise RuntimeError("启动等待超时，请稍后重试。")
        known[str(port)] = fingerprint
        RUNTIME.write_text(json.dumps(known), encoding="utf-8")
    return f"http://127.0.0.1:{port}/front/The%20Court.dc.html"


def main():
    root = tk.Tk()
    root.title("猫皇朝堂")
    root.geometry("510x450")
    root.resizable(False, False)
    panel = ttk.Frame(root, padding=26)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="猫皇朝堂", font=("Microsoft YaHei", 23, "bold")).pack(anchor="w")
    status = tk.StringVar(value="首次使用，填一次 Google AI 密钥。以后双击桌面图标即可进入。")
    ttk.Label(panel, textvariable=status, wraplength=450).pack(anchor="w", pady=(12, 18))
    config = settings()
    api_key = tk.StringVar(value=config.get("api_key", ""))
    model = tk.StringVar(value=config.get("model") or MODEL)
    ttk.Label(panel, text="Google AI API Key（仅保存到本机）").pack(anchor="w")
    entry = ttk.Entry(panel, textvariable=api_key, show="•", width=60)
    entry.pack(fill="x", pady=(5, 12))
    ttk.Label(panel, text="模型").pack(anchor="w")
    ttk.Entry(panel, textvariable=model, width=60).pack(fill="x", pady=(5, 10))
    ttk.Label(panel, text="使用 Google 免费额度；不要启用付费结算。", foreground="#77665a").pack(anchor="w")
    result: list = []

    def poll():
        if not result:
            root.after(150, poll)
            return
        value = result.pop()
        if isinstance(value, Exception):
            status.set("未能启动，可以重试。")
            button.configure(state="normal")
            messagebox.showerror("朝堂未启动", str(value), parent=root)
        else:
            webbrowser.open(value)
            root.destroy()

    def start():
        if not api_key.get().strip():
            messagebox.showinfo("需要密钥", "请先从 Google AI Studio 创建免费项目的 API Key，填入此处。", parent=root)
            return
        current = {"api_key": api_key.get().strip(), "model": model.get().strip() or MODEL}
        DATA.mkdir(exist_ok=True)
        SETTINGS.write_text(json.dumps(current), encoding="utf-8")
        button.configure(state="disabled")
        status.set("正在启动本地朝堂，完成后自动打开页面……")

        def work():
            try:
                result.append(launch(current))
            except Exception as exc:
                result.append(exc)

        threading.Thread(target=work, daemon=True).start()
        root.after(150, poll)

    button = ttk.Button(panel, text="进入朝堂", command=start)
    button.pack(anchor="e", pady=(12, 0))
    if config.get("api_key") and "--configure" not in sys.argv:
        root.after(100, start)
    entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
