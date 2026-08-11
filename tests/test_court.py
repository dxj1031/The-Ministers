"""辩论引擎自检：python tests/test_court.py

强制关掉模型（清空 API key），走兜底路径 —— 模型挂了玩法也必须完整跑完一局。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MINISTERS_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ["MINISTERS_API_KEY"] = ""   # 清掉 .env 里的本地模型，强制走兜底
os.environ["OPENAI_API_KEY"] = ""

from app.back.core import store  # noqa: E402
from app.back.ministers import roster  # noqa: E402
from app.back.services import court  # noqa: E402


def main():
    store.init_db()

    s = court.open_court("要不要辞职去开一家猫咖", "存款够撑 8 个月")
    assert len(s["ministers"]) == 11, len(s["ministers"])
    assert sum(s["tally"].values()) == 11, s["tally"]
    assert s["round"] == 0 and s["status"] == "debating"

    # 模型不可用时每次调用都要留痕，而且标成 fallback —— 不能悄悄降级
    tr = store.list_traces(s["id"])
    assert len(tr) >= 1 and tr[0]["ok"] == 0 and tr[0]["fallback"] == 1, tr[0]

    for i in range(court.ROUNDS_PER_SESSION):
        before = len([t for t in s["turns"] if t["kind"] == "rebuttal"])
        s = court.next_round(s["id"])
        # 每轮必须正好两句对呛：模型少写一句或者自己换人上场，都不能让回合结构塌掉
        after = len([t for t in s["turns"] if t["kind"] == "rebuttal"])
        assert after - before == 2, (i, before, after)
        # 回合数按模型调用次数算：模型少写一句台词也不能让回合白跑一遍（会多花一倍钱）
        assert s["round"] == i + 1, (i, s["round"])
        assert s["rounds_left"] == court.ROUNDS_PER_SESSION - i - 1, s
        assert sum(s["tally"].values()) == 11, s["tally"]

    # 死锁上限：辩了 5 轮不该还有一大半在观望
    assert s["tally"]["undecided"] <= court.MAX_UNDECIDED + 1, s["tally"]

    s = court.decree(s["id"], "silence", lean_delta=0.5)
    assert abs(s["lean"] - 0.5) < 1e-9, s["lean"]
    s = court.decree(s["id"], "banana", lean_delta=0.9)
    assert s["lean"] == 1.0, "lean 必须夹在 [-1,1]"

    s = court.verdict(s["id"], "approve")
    assert s["status"] == "decided" and s["verdict"] == "approve"
    assert s["turns"][-1]["kind"] == "verdict"

    # 每位大臣的每条发言都必须属于名册（emperor 除外），前端按 id 查头像会依赖这点
    ids = set(roster.IDS) | {"emperor"}
    assert all(t["minister"] in ids for t in s["turns"])

    st = store.stats()
    assert st["calls"] >= 3 and st["sessions"] == 1, st

    try:
        court.snapshot("nope")
        raise AssertionError("不存在的 session 应该抛 KeyError")
    except KeyError:
        pass

    malformed_shapes()
    print_ok(s, st)


def malformed_shapes():
    """模型返回的 JSON 形状不对时不能 500 —— 真机上就撞过一次：
    clash 说好是对象数组，模型给了字符串数组，next_round 直接崩。"""
    import app.back.core.llm as llm_mod

    bad = [
        {"ministers": ["fox", "rabbit"]},                       # 该是对象，给了数组
        {"ministers": {"fox": "此事必有蹊跷"}},                   # 该是对象，给了字符串
        {"clash": ["甲说", "乙说"], "lobby": "拉票"},             # 两个都该是对象
        {"clash": [{"minister": "不存在的大臣", "text": "x"}]},   # 大臣 id 不在名册里
        {"clash": None, "lobby": None},
        {"edict": ["不是字符串"]},
        {},
    ]
    real = llm_mod.complete_json
    for shape in bad:
        llm_mod.complete_json = lambda *a, _s=shape, **k: (_s, 0)
        try:
            sid = court.open_court("形状测试", "背景")["id"]
            for _ in range(2):
                court.next_round(sid)
            snap = court.verdict(sid, "shelve")
            assert sum(snap["tally"].values()) == 11, (shape, snap["tally"])
            assert snap["status"] == "decided"
        finally:
            llm_mod.complete_json = real
    print(f"malformed OK · {len(bad)} 种畸形输出都没崩")


def print_ok(s, st):

    print(f"court OK · {len(s['turns'])} turns · {st['calls']} calls · tally={s['tally']}")


if __name__ == "__main__":
    main()
