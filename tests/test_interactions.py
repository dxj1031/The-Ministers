"""圣旨和回应的回归检查：python tests/test_interactions.py。"""
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / f"interaction-test-{uuid.uuid4().hex}.db"
os.environ["MINISTERS_DB"] = str(DB)
os.environ["MINISTERS_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

from app.back.core import store  # noqa: E402
from app.back.services import court  # noqa: E402


def main():
    store.init_db()
    s = court.open_court("是否取消每周例会", "团队跨时区")
    assert s["fallback"] is True, "模型不可用必须明确告诉前端"
    sid = s["id"]

    court.decree(sid, "banana")
    before = len(store.get_session(sid)["turns"])
    s = court.next_round(sid)
    duel = [t for t in s["turns"][before:] if t["kind"] == "rebuttal"]
    assert duel[0]["minister"] == "banana", "宣香蕉必须真正改变发言人"
    assert duel[0]["target"] == duel[1]["minister"]
    assert duel[1]["target"] == "banana", "对呛需要双向的回应对象"

    # 消费过的圣旨不能在后续回合反复调用香蕉。
    expected = court._duel_pair(store.current_stances(sid), s["round"])
    before = len(s["turns"])
    s = court.next_round(sid)
    assert tuple(t["minister"] for t in s["turns"][before:]
                 if t["kind"] == "rebuttal") == expected

    court.decree(sid, "swap")
    expected = court._duel_pair(store.current_stances(sid), s["round"] + 1)
    before = len(store.get_session(sid)["turns"])
    s = court.next_round(sid)
    assert tuple(t["minister"] for t in s["turns"][before:]
                 if t["kind"] == "rebuttal") == expected

    # 没被说服也要回复，不能把“抵抗”从朝堂实录里删掉。
    store.add_turn(sid, "sheep", "opening", "undecided", "臣暂不站队", influence=.3)
    rabbit_side = store.current_stances(sid)["rabbit"]["stance"]
    store.add_turn(sid, "rabbit", "opening", rabbit_side, "臣提议试行", influence=.1)
    before = len(store.get_session(sid)["turns"])
    with patch.object(court, "_politics", return_value=("lobby", ("rabbit", "sheep"))), \
            patch.object(court, "_seed", return_value=0), \
            patch.object(court, "MAX_UNDECIDED", 99):
        s = court.next_round(sid)
    reply = next(t for t in s["turns"][before:]
                 if t["kind"] == "lobby" and t["minister"] == "sheep")
    assert reply["target"] == "rabbit" and reply["stance"] == "undecided"
    assert reply["text"].strip()

    court.decree(sid, "custom", text="请考虑异步周报可能遗漏的问题")
    real = court.llm.complete_json
    with patch.object(court.llm, "complete_json", wraps=real) as complete:
        court.next_round(sid)
    messages = next(c.args[0] for c in complete.call_args_list if c.kwargs.get("op") == "speak")
    assert "请考虑异步周报可能遗漏的问题" in messages[-1]["content"]
    print("interactions OK: actual speaker selection, one-use commands, reply targets, resistance, decree context, fallback visibility")


if __name__ == "__main__":
    try:
        main()
    finally:
        DB.unlink(missing_ok=True)
