"""Echo participates in real debate, can be addressed/dismissed, and never double-votes."""
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / f"parrot-test-{uuid.uuid4().hex}.db"
os.environ["MINISTERS_DB"] = str(DB)
os.environ["MINISTERS_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
from app.back.core import store
from app.back.services import court


def main():
    store.init_db()
    s = court.open_court("是否异步周报", "团队跨时区，紧急情况需同步。")
    sid = s["id"]
    assert len(s["turns"]) == 12 and sum(s["tally"].values()) == 12
    assert any(t["minister"] == "parrot" and t["kind"] == "opening" for t in s["turns"])
    before = len(s["turns"])
    s = court.next_round(sid)
    assert any(t["minister"] == "parrot" and t["kind"] in {"floor", "lobby", "rebuttal"} for t in s["turns"][before:])
    court.decree(sid, "question", text="应声，请解释紧急通道如何保留？", target="parrot")
    s = court.respond(sid)
    assert s["turns"][-2]["minister"] == "parrot" and s["turns"][-2]["kind"] == "reply"
    stances_before = store.current_stances(sid)
    s = court.verdict(sid, "approve")
    assert s["turns"][-1]["minister"] == "parrot" and s["turns"][-1]["kind"] == "verdict"
    assert len(s["ministers"]) == 12 and sum(s["tally"].values()) == 12
    assert store.current_stances(sid)["parrot"] == stances_before["parrot"], "Reading the verdict cannot reset Echo's debate stance"

    s = court.open_court("是否异步周报", "团队跨时区")
    sid = s["id"]
    s = court.decree(sid, "dismiss")
    assert len(s["ministers"]) == 11 and sum(s["tally"].values()) == 11
    before = len(s["turns"])
    s = court.next_round(sid)
    assert all(t["minister"] != "parrot" and t.get("target") != "parrot" for t in s["turns"][before:])
    try:
        court.decree(sid, "question", text="请回答", target="parrot")
        raise AssertionError("A dismissed minister cannot receive a new question")
    except ValueError:
        pass
    s = court.verdict(sid, "approve")
    assert s["turns"][-1]["minister"] == "emperor"
    print("parrot OK: 12 real opening voices/votes, first group debate, direct reply, no duplicate verdict vote, dismissal")


if __name__ == "__main__":
    try:
        main()
    finally:
        DB.unlink(missing_ok=True)
