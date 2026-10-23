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


def test_dismiss_echo():
    """罢免应声：朝堂少一个声音，但没有人再顺着你。"""
    s = court.open_court("要不要辞职去开一家猫咖", "存款够撑 8 个月", lean_open=0.5)
    s = court.decree(s["id"], "silence", lean_delta=0.3)
    assert len(s["ministers"]) == 12 and s["ministers"][-1]["id"] == roster.PARROT
    assert s["echo_out"] is False

    s = court.decree(s["id"], "dismiss")
    assert s["echo_out"] is True
    assert len(s["ministers"]) == 11, "罢免之后名册里不该还有应声"
    assert all(m["id"] != roster.PARROT for m in s["ministers"])
    assert abs(s["lean"] - 0.3) < 1e-9, "罢免不是改主意，不该动 lean"
    assert sum(s["tally"].values()) == 11, "应声本来就没有票，罢免也不该改票数"
    assert s["turns"][-1]["kind"] == "decree", "罢免要在朝堂记录里留一行"

    # 判词换人念：没有谀臣了，判词就只是判词
    s = court.verdict(s["id"], "approve")
    assert s["turns"][-1]["minister"] == "emperor", s["turns"][-1]
    assert s["turns"][-1]["kind"] == "verdict"
    # 谏言不受影响：异议是辩论的一部分，不是谀臣的陪衬
    assert s["remonstrance"] is not None


def test_mirror_and_confirm_rate():
    """朝堂镜三行，以及「裁决是不是照着开场倾向走的」怎么算。"""
    # 开场偏赞成，最后准奏 —— 这就是一次「确认」
    s = court.open_court("要不要辞职去开一家猫咖", "存款够撑 8 个月", lean_open=0.6)
    for _ in range(2):
        s = court.next_round(s["id"])
    s = court.verdict(s["id"], "approve")
    assert s["lean_open"] == 0.6 and store.get_session(s["id"])["verdict_aligned"] == 1

    m = s["mirror"]
    stances = {k: v for k, v in store.current_stances(s["id"]).items()
               if k not in ("emperor", roster.PARROT)}
    pro = sorted([x for x, v in stances.items() if v["stance"] == "pro"],
                 key=lambda x: -stances[x]["influence"])[:3]
    assert [x["minister"] for x in m["pushed"]] == pro, (m["pushed"], pro)
    assert all(x["text"] for x in m["pushed"]), "推你过去的那几位要附原话"
    # 「你忽略的」就是谏言，不另算一套
    assert m["ignored"] == s["remonstrance"]
    assert m["confirm"]["n"] >= 1 and 0 <= m["confirm"]["rate"] <= 1

    # 带着倾向进来却搁置：记 0，那正是「这次没被自己的倾向牵着走」
    s2 = court.open_court("该不该先给她发消息", "", lean_open=-0.5)
    s2 = court.verdict(s2["id"], "shelve")
    assert store.get_session(s2["id"])["verdict_aligned"] == 0

    # 开场没倾向 → 没有「确认」可言，记 NULL 而不是 0
    s3 = court.open_court("要不要把年终奖全买显卡", "")
    s3 = court.verdict(s3["id"], "approve")
    assert store.get_session(s3["id"])["verdict_aligned"] is None, "开场没倾向不该算成没确认"

    # 没裁决的局不出镜
    s4 = court.open_court("过年要不要带对象回家", "", lean_open=0.3)
    assert s4["mirror"] is None


def test_user_read_is_pinned_and_targeted():
    """用户改过的字段，拾荒改不动；而且这些话只给看得见的那几位大臣。"""
    s = court.open_court("要不要辞职去开一家猫咖", "存款够撑 8 个月")
    store.add_user_read(s["id"], "raccoon",
                        {"anxiety": "存款见底", "impulse": "明天就辞",
                         "stake": "八个月生活费", "deadline": "房东涨租"})
    store.add_user_read(s["id"], "user", {"anxiety": "怕被人笑话", "impulse": "",
                                          "stake": "", "deadline": ""})

    # 按字段取最新：用户只改了一项，拾荒整理的另外三项不该被抹掉
    m = store.user_read()
    assert m["anxiety"] == {"text": "怕被人笑话", "source": "user"}, m
    assert m["impulse"]["text"] == "明天就辞" and m["impulse"]["source"] == "raccoon", m

    # 断了模型，拾荒整理只会回退到档案原样 —— 用户钉死的那项必须还在
    court.read_user(s["id"])
    assert store.user_read()["anxiety"]["source"] == "user", "用户定的被模型盖掉了"

    # 定向：维斯帕看得到怕什么和赌注，跺脚将军看不到
    fox = court._private_block(["fox"])
    assert "怕被人笑话" in fox and "八个月生活费" in fox, fox
    assert "明天就辞" not in fox, "维斯帕不该看见冲动那一项"
    assert court._private_block(["snake", "banana", "octopus"]) == "", "这几位不该拿到用户状态"
    assert "明天就辞" in court._private_block(["rabbit"])


def test_lean_does_not_reach_debaters():
    """皇帝倾向不许影响任何一位辩论大臣 —— 硬约束 3 的可执行版本。

    倒戈判定里掺了 _seed(session_id, ...)，而 session_id 是随机的 uuid，
    所以两局朝会本来就不会逐字一样。这里把 _seed 钉死，剩下的唯一变量就是 lean：
    三个 lean 跑出完全相同的立场序列，才说明 lean 真的碰不到辩论。
    """
    real_seed = court._seed
    court._seed = lambda *parts: 42
    try:
        runs = []
        for lean in (0.0, 0.8, -0.8):
            s = court.open_court("要不要辞职去开一家猫咖", "存款够撑 8 个月")
            store.set_lean(s["id"], lean)
            for _ in range(court.ROUNDS_PER_SESSION):
                s = court.next_round(s["id"])
            s = court.verdict(s["id"], "shelve")
            runs.append([(t["minister"], t["kind"], t["stance"]) for t in s["turns"]
                         if t["minister"] != roster.PARROT])
        assert runs[0] == runs[1] == runs[2], "lean 改变了辩论大臣的立场序列"
        assert len(runs[0]) > 11, runs[0]       # 别让一局空跑把断言变成废话
    finally:
        court._seed = real_seed


def main():
    store.init_db()

    s = court.open_court("要不要辞职去开一家猫咖", "存款够撑 8 个月")
    assert len(s["ministers"]) == 12, len(s["ministers"])      # 十一位辩论 + 应声
    assert sum(s["tally"].values()) == 11, s["tally"]          # 应声没有票
    assert s["round"] == 0 and s["status"] == "debating"

    # 应声不写 turn：它的立场是读取时由 lean 算的，不该在朝会记录里留痕
    assert all(t["minister"] != roster.PARROT for t in s["turns"]), "应声不该有发言记录"
    echo = next(m for m in s["ministers"] if m["id"] == roster.PARROT)
    assert (echo["stance"], echo["influence"]) == ("undecided", 0.0), echo
    assert s["ministers"][-1]["id"] == roster.PARROT, "应声排在名册末位"

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
    # 皇帝一表态，应声立刻跟过去 —— 它是唯一一个吃 lean 的大臣
    echo = next(m for m in s["ministers"] if m["id"] == roster.PARROT)
    assert (echo["stance"], echo["influence"]) == ("pro", 0.5), echo
    assert sum(s["tally"].values()) == 11, "应声倒过去也不该改票数"

    s = court.decree(s["id"], "banana", lean_delta=-1.4)
    assert abs(s["lean"] + 0.9) < 1e-9, s["lean"]
    echo = next(m for m in s["ministers"] if m["id"] == roster.PARROT)
    assert (echo["stance"], echo["influence"]) == ("con", 0.9), "皇帝转向，应声跟着转"

    s = court.decree(s["id"], "banana", lean_delta=-0.9)
    assert s["lean"] == -1.0, "lean 必须夹在 [-1,1]"

    turns_before = len(s["turns"])
    s = court.verdict(s["id"], "approve")
    assert s["status"] == "decided" and s["verdict"] == "approve"
    assert s["turns"][-1]["kind"] == "verdict"
    # 判词由应声念：说话人必须写在记录里，前端靠它署名
    assert s["turns"][-1]["minister"] == roster.PARROT, s["turns"][-1]

    # 谏言：裁决是准奏，所以进谏的必须是终局反对、影响力最高的那位
    r = s["remonstrance"]
    cons = {m: v for m, v in store.current_stances(s["id"]).items() if v["stance"] == "con"}
    assert r and r["stance"] == "con" and r["minister"] in cons, r
    assert r["influence"] == max(v["influence"] for v in cons.values()), r
    # 原话必须是它真说过的，而且是它最后一次发言 —— 重新生成就是编造它没说过的话
    said = [t for t in s["turns"] if t["minister"] == r["minister"]
            and t["kind"] in ("opening", "rebuttal", "lobby")]
    assert r["text"] == said[-1]["text"].strip(), (r["text"], said[-1]["text"])
    # 裁决只新增一行（判词）。谏言是对已有发言的视角，不落 turn 表 ——
    # 把原话再存一遍，评估那边就会多出一条「重复台词」，而那不是模型的锅。
    assert len(s["turns"]) == turns_before + 1, (turns_before, len(s["turns"]))

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
    test_user_read_is_pinned_and_targeted()
    test_mirror_and_confirm_rate()
    test_dismiss_echo()
    test_lean_does_not_reach_debaters()   # 要多开三局，放在 sessions 断言之后
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
