"""把本地跑出来的真实数据导成一份静态快照，供 GitHub Pages 上的监控台读取。

    python tools/export_snapshot.py

监控台先探 /api/health；探不到就退回这份 snapshot.json。
所以同一个 index.html 在本地是实时看板，在 Pages 上是一份带真数据的作品展示。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.back.core import store  # noqa: E402

OUT = ROOT / "snapshot.json"
MAX_SESSIONS = 8          # 展示够用就行，别把整个库塞进仓库
MAX_TRACES = 40


def main():
    sessions = store.list_sessions(MAX_SESSIONS)
    detail = {}
    for s in sessions:
        d = store.get_session(s["id"])
        d["traces"] = store.list_traces(s["id"], MAX_TRACES)
        d["retrievals"] = store.list_retrievals(s["id"])
        detail[s["id"]] = d

    snap = {
        "exported_at": store.now(),
        "health": {"ok": True, "db": "snapshot"},
        "stats": store.stats(),
        "sessions": sessions,
        "detail": detail,
    }
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"{OUT.name}: {len(sessions)} 场朝会 · {snap['stats']['calls']} 次调用 · {kb:.0f} KB")
    if kb > 800:
        print("提示：快照偏大，调小 MAX_SESSIONS / MAX_TRACES")


if __name__ == "__main__":
    main()
