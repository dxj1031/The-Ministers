"""数据层自检：python tests/test_store.py

不用 pytest，跑起来不报错就是过。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MINISTERS_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")

from app.back.core import llm, store  # noqa: E402


def main():
    store.init_db()

    sid = store.create_session("要不要辞职", "攒了 8 个月生活费", "zh")
    assert store.get_session(sid)["topic"] == "要不要辞职"
    assert store.get_session("nope") is None

    t1 = store.add_turn(sid, "fox", "opening", "con", "此事必有蹊跷。", influence=0.7)
    t2 = store.add_turn(sid, "rabbit", "opening", "pro", "现在就辞！", influence=0.5)
    turns = store.get_session(sid)["turns"]
    assert [t["seq"] for t in turns] == [1, 2], turns  # seq 必须从 1 连续递增
    assert turns[0]["minister"] == "fox"

    store.add_trace("speak", "gpt-4o-mini", session_id=sid, turn_id=t1, minister="fox",
                    prompt_tokens=1000, completion_tokens=500, latency_ms=800,
                    cost_usd=llm.price_of("gpt-4o-mini", 1000, 500))
    store.add_trace("speak", "gpt-4o-mini", session_id=sid, turn_id=t2, minister="rabbit",
                    latency_ms=200, ok=False, fallback=True, error="timeout")

    st = store.stats()
    assert st["calls"] == 2 and st["sessions"] == 1, st
    assert st["errors"] == 1 and st["fallbacks"] == 1, st
    assert abs(st["cost_usd"] - (1000 * 0.15 + 500 * 0.60) / 1e6) < 1e-12, st["cost_usd"]
    assert st["avg_latency_ms"] == 500, st
    assert [o["op"] for o in st["by_op"]] == ["speak"]

    # 未知模型不能炸，只是算 0 成本
    assert llm.price_of("some-local-model", 999, 999) == 0.0

    assert len(store.list_traces(sid)) == 2
    assert store.list_traces("other") == []

    store.end_session(sid, "approve")
    s = store.list_sessions()[0]
    assert s["status"] == "decided" and s["verdict"] == "approve"
    assert s["turns"] == 2 and s["calls"] == 2, s

    print("store OK")


if __name__ == "__main__":
    main()
