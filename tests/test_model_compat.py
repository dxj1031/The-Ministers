"""Real provider response shapes must preserve arguments and flag actual fallback."""
import json
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / f"compat-test-{uuid.uuid4().hex}.db"
os.environ["MINISTERS_DB"] = str(DB)
from app.back.core import llm, store
from app.back.services import court


def main():
    store.init_db()
    sid = store.create_session("是否异步周报", "团队跨时区", "zh")
    with patch.object(llm, "complete", return_value=('[{"ministers":{"fox":{"text":"先试行"}}}]', 1)):
        result, _ = llm.complete_json([], fallback={}, op="stance", session_id=sid)
        assert result["ministers"]["fox"]["text"] == "先试行"
    with patch.object(llm, "complete", return_value=('[{},{}]', 1)):
        result, _ = llm.complete_json([], fallback={"failed": True}, op="stance", session_id=sid)
        assert result["failed"]
    assert court.snapshot(sid)["fallback"], "Parse fallback must be visible in the UI snapshot"
    ministers = {mid: {"stance": "pro", "text": "先试行异步周报", "reason": "跨时区同步成本较高，先试行再检查遗漏。", "source": "context-1"}
                 for mid in court.roster.DEBATERS}
    with patch.object(court, "read_user"), patch.object(court.library, "add_facts"), \
            patch.object(llm, "complete_json", return_value=(ministers, 1)):
        s = court.open_court("是否异步周报", "团队跨时区")
        assert len(s["turns"]) == 12 and not s["fallback"]
        assert all(t["text"] == "先试行异步周报" and t["detail"]["reason"] for t in s["turns"])
    with patch.object(court, "read_user"), patch.object(court.library, "add_facts"), \
            patch.object(llm, "complete_json", return_value=({"unexpected": {}}, 1)):
        s = court.open_court("是否异步周报", "团队跨时区")
        assert s["fallback"], "Missing ministers must not look like a successful live model response"
    print("model compatibility OK: singleton object wrapper, direct minister map, arguments preserved, parse/shape fallback visible")


if __name__ == "__main__":
    try:
        main()
    finally:
        DB.unlink(missing_ok=True)
