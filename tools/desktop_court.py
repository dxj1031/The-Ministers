"""Windows desktop entry: first-run Google AI setup, hidden API, then browser."""
import json
import hashlib
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import Request, urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SETTINGS = DATA / "desktop-google.json"  # data/ is ignored by Git.
RUNTIME = DATA / "desktop-runtime.json"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MODEL = "gemini-3.5-flash-lite"
OLLAMA = "http://127.0.0.1:11434"


def gpu_5060() -> dict | None:
    utility = shutil.which("nvidia-smi")
    if not utility:
        return None
    try:
        result = subprocess.run([utility, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for row in result.stdout.splitlines():
            name, _, memory = row.partition(",")
            if "5060 ti" in name.lower():
                return {"name": name.strip(), "memory": int(memory.strip())}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def ollama_json(path: str, payload: dict | None = None, timeout: int = 3) -> dict:
    request = Request(OLLAMA + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def local_model(card: dict, config: dict) -> dict:
    try:
        tags = ollama_json("/api/tags")
    except (OSError, ValueError):
        executable = shutil.which("ollama")
        if not executable:
            candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
            executable = str(candidate) if candidate.is_file() else None
        if not executable:
            raise RuntimeError("已检测到 5060 Ti，请先安装 Ollama。")
        DATA.mkdir(exist_ok=True)
        with (DATA / "desktop-ollama.log").open("ab") as log:
            subprocess.Popen([executable, "serve"], stdout=log, stderr=log,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(20):
            try:
                tags = ollama_json("/api/tags")
                break
            except (OSError, ValueError):
                time.sleep(1)
        else:
            raise RuntimeError("Ollama 未能启动，请打开 Ollama 后重试。")
    model = config.get("local_model") or ("qwen2.5:14b" if card["memory"] >= 12000 else "qwen2.5:7b")
    if not any(m.get("name") == model for m in tags.get("models", [])):
        raise RuntimeError(f"已检测到 5060 Ti，请先在 Ollama 下载模型 {model}，然后再双击入口。")
    # Empty generation preloads the model without sending a user conversation.
    ollama_json("/api/generate", {"model": model, "prompt": "", "stream": False, "keep_alive": "30m"}, timeout=120)
    loaded = next((m for m in ollama_json("/api/ps").get("models", []) if m.get("name") == model), {})
    if loaded.get("size_vram", 0) <= 0:
        raise RuntimeError("检测到 5060 Ti，但 Ollama 没有使用显存。请检查显卡驱动与 Ollama；本次没有改用云端。")
    return {"base_url": OLLAMA + "/v1", "api_key": "ollama", "model": model, "engine": "local"}


def resolve_model(config: dict) -> dict:
    mode = config.get("mode", "auto")
    if mode in {"auto", "local"}:
        card = gpu_5060()
        if card:
            return local_model(card, config)
        if mode == "local":
            raise RuntimeError("未检测到已连接的 5060 Ti。请连接显卡后重试。")
    if not config.get("api_key"):
        raise RuntimeError("未检测到 5060 Ti。如需用 Google AI，请在设置中填写 API Key；本地显卡模式无需密钥。")
    return {"base_url": BASE_URL, "api_key": config["api_key"], "model": config.get("model") or MODEL, "engine": "google"}


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
    config = resolve_model(config)
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
        env.update(MINISTERS_BASE_URL=config["base_url"], MINISTERS_API_KEY=config["api_key"],
                   MINISTERS_MODEL=config.get("model") or MODEL, MINISTERS_TIMEOUT="180",
                   MINISTERS_DB=str(DATA / "ministers.db"))
        # Cloud-only settings must not turn the private localhost app into a hosted service.
        env.pop("RENDER", None)
        env["MINISTERS_ACCESS_KEY"] = ""
        if config["engine"] == "local":
            env["MINISTERS_EMBED_MODEL"] = "bge-m3:latest"
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
    root.geometry("510x530")
    root.resizable(False, False)
    panel = ttk.Frame(root, padding=26)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="猫皇朝堂", font=("Microsoft YaHei", 23, "bold")).pack(anchor="w")
    status = tk.StringVar(value="连接 5060 Ti 时优先用本机显卡，不需要云模型密钥。")
    ttk.Label(panel, textvariable=status, wraplength=450).pack(anchor="w", pady=(12, 18))
    config = settings()
    modes = {"自动（5060 Ti 优先）": "auto", "仅本地显卡": "local", "Google AI": "google"}
    selection = tk.StringVar(value=next((label for label, value in modes.items() if value == config.get("mode", "auto")), next(iter(modes))))
    ttk.Label(panel, text="运行方式").pack(anchor="w")
    ttk.Combobox(panel, textvariable=selection, values=list(modes), state="readonly").pack(fill="x", pady=(5, 12))
    api_key = tk.StringVar(value=config.get("api_key", ""))
    model = tk.StringVar(value=config.get("model") or MODEL)
    ttk.Label(panel, text="Google AI API Key（本地显卡无需填写）").pack(anchor="w")
    entry = ttk.Entry(panel, textvariable=api_key, show="•", width=60)
    entry.pack(fill="x", pady=(5, 12))
    ttk.Label(panel, text="Google 模型（仅云端模式使用）").pack(anchor="w")
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
        if modes[selection.get()] == "google" and not api_key.get().strip():
            messagebox.showinfo("需要密钥", "请先从 Google AI Studio 创建免费项目的 API Key，填入此处。", parent=root)
            return
        current = {"api_key": api_key.get().strip(), "model": model.get().strip() or MODEL, "mode": modes[selection.get()]}
        DATA.mkdir(exist_ok=True)
        SETTINGS.write_text(json.dumps(current), encoding="utf-8")
        button.configure(state="disabled")
        status.set("正在检测显卡、加载模型并启动朝堂，完成后自动打开页面……")

        def work():
            try:
                result.append(launch(current))
            except Exception as exc:
                result.append(exc)

        threading.Thread(target=work, daemon=True).start()
        root.after(150, poll)

    button = ttk.Button(panel, text="进入朝堂", command=start)
    button.pack(anchor="e", pady=(12, 0))
    if "--configure" not in sys.argv:
        root.after(100, start)
    entry.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
