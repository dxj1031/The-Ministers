"""词条墙、群辩、论据与政治事件的确定性回归。"""
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / f"experience-test-{uuid.uuid4().hex}.db"
os.environ["MINISTERS_DB"] = str(DB)
os.environ["MINISTERS_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

from app.back.core import store  # noqa: E402
from app.back.services import court  # noqa: E402


def main():
    store.init_db()
    real = court.llm.complete_json
    captured = []
    sides = {"fox": "con", "rabbit": "pro", "horse": "pro", "collie": "pro",
             "raccoon": "con", "snake": "con", "fish": "undecided", "sheep": "undecided",
             "moth": "con", "banana": "pro", "octopus": "undecided"}
    argument = {"text": "先试行，再检查遗漏", "reason": "如果异步消息没有确认，紧急问题可能被漏掉，因此要保留升级通道。",
                "source": "context-1", "evidence": "模型伪造的出处不应该进入记录"}

    def complete(messages, **kw):
        _, trace = real(messages, **kw)
        captured.append((kw["op"], messages))
        if kw["op"] == "stance":
            return {"ministers": {m: {**argument, "stance": sides[m]} for m in court.roster.DEBATERS}}, trace
        if kw["op"] == "speak":
            return {"clash": [argument, argument], "floor": [argument, argument],
                    "lobby": {**argument, "reply": "臣愿明确回应这个条件", "reply_reason": argument["reason"], "reply_source": "context-1"}}, trace
        if kw["op"] == "reply":
            return {"replies": [argument, argument]}, trace
        return {}, trace

    with patch.object(court.llm, "complete_json", side_effect=complete):
        s = court.open_court("是否把例会改成异步周报", "团队跨时区。紧急问题可能遗漏。")
        sid = s["id"]
        d = s["turns"][0]["detail"]
        assert d["reason"] and d["evidence"] == "团队跨时区"
        assert "伪造" not in d["evidence"]
        assert court._argument({"reason": "可能如此", "source": "invented"}, {})["basis"] == "assumption"

        for rnd in range(3):
            before = len(s["turns"])
            s = court.next_round(sid)
            batch = s["turns"][before:]
            assert len({t["minister"] for t in batch}) >= 4, "群辩必须有至少四位不同参与者"
            assert sum(t["kind"] == "floor" for t in batch) == 2
            assert all(t["detail"].get("reason") for t in batch)
            assert all(t["target"] for t in batch)
            if rnd == 1:
                assert any(t["detail"].get("outcome") == "allied" for t in batch)
            if rnd == 2:
                assert any(t["detail"].get("move") == "threaten" for t in batch)

        # 明确建立同盟，随后成功拉拢其中一位，背盟需要有真实的旧关系可撤销。
        current = store.current_stances(sid)
        a, b = next((a, b) for a in sides for b in sides if a != b and current[a]["stance"] == current[b]["stance"] != "undecided")
        store.add_turn(sid, b, "lobby", current[b]["stance"], "臣愿结盟", influence=current[b]["influence"], target=a,
                       detail={"move": "ally", "outcome": "allied", "round": 3})
        enemy = next(m for m in sides if current[m]["stance"] not in (current[b]["stance"], "undecided"))
        with patch.object(court, "_politics", return_value=("defect", (enemy, b))), patch.object(court, "_seed", return_value=99):
            s = court.next_round(sid)
        betrayal = next(t for t in reversed(s["turns"]) if t["detail"].get("outcome") == "defected")
        assert betrayal["detail"]["former_allies"] and betrayal["detail"]["reply_to"]
        assert not any(b in p for p in s["alliances"]), "背盟要真实撤销旧同盟"

        s = court.decree(sid, "question", text="你准备怎样避免消息遗漏？", target="fox")
        question_seq = s["turns"][-1]["seq"]
        round_before = s["round"]
        s = court.respond(sid)
        replies = [t for t in s["turns"] if t["kind"] == "reply"]
        assert replies[0]["minister"] == "fox"
        assert all(t["target"] == "emperor" and t["detail"]["reply_to"] == question_seq for t in replies)
        assert s["round"] == round_before
        assert len(court.respond(sid)["turns"]) == len(s["turns"]), "重试回应不能重复发言"

        # 在相同立场、影响力与种子下，风险词条使谨慎角色的交涉越过阈值；切掉后不再生效。
        results = []
        for add_risk in (False, True):
            case = court.open_court("是否异步周报", "团队跨时区。")
            case_id = case["id"]
            store.add_turn(case_id, "fox", "opening", "con", "仍有风险", influence=.7)
            if add_risk:
                case = court.factor(case_id, "紧急信息遗漏", "risk")
                entry = case["factors"][0]
                assert court._factor_force(store.get_session(case_id), "fox") == (.1, [entry["id"]])
                off = court.factor(case_id, factor_id=entry["id"], active=False)
                assert "factor-" + entry["id"] not in court._sources(store.get_session(case_id))
                assert court._factor_force(store.get_session(case_id), "fox") == (0, [])
                court.factor(case_id, factor_id=entry["id"], active=True)
                assert any(t["detail"].get("outcome") == "cut" for t in off["turns"])
            with patch.object(court, "_politics", return_value=("lobby", ("fox", "sheep"))), \
                    patch.object(court, "_seed", return_value=30), patch.object(court, "MAX_UNDECIDED", 99):
                case = court.next_round(case_id)
            result = next(t for t in reversed(case["turns"]) if t["minister"] == "sheep" and t["kind"] == "lobby")
            results.append(result["stance"])
            assert bool(result["detail"]["drivers"]["factors"]) == add_risk
        assert results == ["undecided", "con"], results
        assert any("active=false" in str(messages) for op, messages in captured if op == "speak")
        from fastapi.testclient import TestClient
        from app.back.main import app
        with TestClient(app) as client:
            url = f"/api/court/{case_id}"
            added = client.post(url + "/factors", json={"text": "必须保留紧急升级通道", "kind": "constraint"})
            assert added.status_code == 200 and added.json()["factors"][-1]["kind"] == "constraint"
            assert client.post(url + "/factors", json={"factor_id": "missing", "active": False}).status_code == 422
            assert client.post(url + "/decree", json={"kind": "question", "text": "为什么", "target": "missing"}).status_code == 422
            assert client.post(url + "/decree", json={"kind": "question", "text": "怎样验证试行结果？", "target": "collie"}).status_code == 200
            answered = client.post(url + "/respond", json={})
            assert answered.status_code == 200 and answered.json()["turns"][-2]["minister"] == "collie"
    print("experience OK: grounded arguments, group debate, alliances, pressure, betrayal, immediate replies, editable factors and causal stance changes")


if __name__ == "__main__":
    try:
        main()
    finally:
        DB.unlink(missing_ok=True)
