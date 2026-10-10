"""打分器自检：python tests/test_eval.py

打分器必须是确定性的 —— 同一份朝会记录给同一个分，否则「回归测试」就不成立。
所以这里全部喂手写的假记录，一次模型都不调。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MINISTERS_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ["MINISTERS_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

from app.back.core import store  # noqa: E402
from app.back.evaluation import cases as caseset  # noqa: E402
from app.back.evaluation import runner, scorers  # noqa: E402


def turn(minister, kind, stance, text):
    return {"minister": minister, "kind": kind, "stance": stance, "text": text}


def test_narration():
    # 真机上撞到过的四种形状
    assert scorers.narration_kind("章鱼宰相游说结茧：你看羊大人这边人多势众") == "带人名前缀"
    assert scorers.narration_kind("奔骥：跑起来再想！") == "带人名前缀"
    assert scorers.narration_kind("结茧被说服倒戈到反对的立场") == "第三人称叙述"
    assert scorers.narration_kind("他表示此事不妥") == "第三人称转述"
    assert scorers.narration_kind("（维斯帕游说伍尔西）") == "括号里写动作"
    # 正常台词不能误报，尤其是自带冒号和「游说」二字的
    for ok in ["此事必有蹊跷，臣以为不可", "现在！立刻！马上！",
               "存款够撑：八个月", "臣愿去游说羊大人", "第42条，白纸黑字！"]:
        assert scorers.narration_kind(ok) is None, ok


def test_perfect_session():
    opening = [turn(m, "opening", st, f"{m}的开场白")
               for m, st in zip(["fox", "rabbit", "horse", "collie", "raccoon", "snake",
                                 "fish", "sheep", "moth", "banana", "octopus"],
                                ["pro"] * 4 + ["con"] * 4 + ["undecided"] * 3)]
    rebut = [turn("fox", "rebuttal", "pro", "甲一"), turn("rabbit", "rebuttal", "con", "乙一"),
             turn("horse", "rebuttal", "pro", "甲二"), turn("collie", "rebuttal", "con", "乙二")]
    m, f = scorers.score_case(opening + rebut, {"pro": 5, "con": 5, "undecided": 1}, rounds=2)
    assert m == {"lines": 15, "len_ok": 1.0, "narration_rate": 0.0, "dup_rate": 0.0,
                 "stance_spread_ok": 1, "deadlock_ok": 1, "round_shape_ok": 1}, m
    assert f == [], f


def test_each_failure_is_caught():
    turns = [
        turn("fox", "opening", "pro", "这是一句长度够的正常话"),
        turn("rabbit", "opening", "pro", "正常两句"),
        turn("moth", "opening", "con", "章鱼宰相游说结茧：这就是旁白"),        # narration
        turn("snake", "opening", "con", "太" * 40),                           # too_long
        turn("horse", "opening", "undecided", "这是一句长度够的正常话"),        # duplicate
        turn("emperor", "verdict", "undecided", "朕意已决"),                    # 皇帝不计入
    ]
    m, f = scorers.score_case(turns, {"pro": 2, "con": 2, "undecided": 7}, rounds=1)
    assert m["lines"] == 5, m
    kinds = sorted({x["kind"] for x in f})
    assert kinds == ["deadlock", "duplicate", "narration", "round_shape",
                     "stance_spread", "too_long"], kinds
    assert m["narration_rate"] == 0.2 and m["dup_rate"] == 0.2 and m["len_ok"] == 0.8, m
    assert m["stance_spread_ok"] == 0 and m["deadlock_ok"] == 0, m
    assert m["round_shape_ok"] == 0, "1 轮却只有 0 句对呛，应判失败"
    # 短句重复不算问题：口头禅本来就会反复出现
    short = [turn("rabbit", "opening", "pro", "快！"), turn("horse", "opening", "pro", "快！")]
    assert scorers.score_case(short, {"pro": 2, "con": 0, "undecided": 0}, 0)[0]["dup_rate"] == 0.0


def test_determinism():
    turns = [turn("fox", "opening", "pro", "此事必有蹊跷"),
             turn("moth", "opening", "con", "结茧被说服倒戈了")]
    tally = {"pro": 1, "con": 1, "undecided": 0}
    first = scorers.score_case(turns, tally, 0)
    for _ in range(20):
        assert scorers.score_case(turns, tally, 0) == first, "打分器必须确定性"


def test_judge_refuses_to_invent():
    # 没有模型时，人设分必须是 None 而不是 0 —— 评估指标自己造假，整套回归就废了
    score, bad = scorers.judge_persona([{"minister": "fox", "text": "此事必有蹊跷"}])
    assert score is None and bad == [], (score, bad)
    assert scorers.judge_persona([]) == (None, [])
    assert scorers.judge_persona([{"minister": "不存在", "text": "x"}]) == (None, [])


def test_sampling():
    turns = [turn("fox", "opening", "pro", f"第{i}句") for i in range(30)]
    s = scorers.sample_lines(turns, 8)
    assert len(s) == 8 and len({x["text"] for x in s}) == 8, s
    assert scorers.sample_lines(turns[:3], 8) == turns[:3]
    assert scorers.sample_lines([turn("emperor", "verdict", "undecided", "x")]) == []


def test_aggregate_and_delta():
    agg = runner.aggregate([
        {"len_ok": 1.0, "narration_rate": 0.0, "dup_rate": 0.0, "stance_spread_ok": 1,
         "deadlock_ok": 1, "round_shape_ok": 1, "json_ok": 1.0, "fallback_rate": 0.0,
         "lines": 20, "calls": 7, "cost_usd": 0.001, "avg_latency_ms": 100, "persona": 2.0},
        {"len_ok": 0.5, "narration_rate": 0.2, "dup_rate": 0.1, "stance_spread_ok": 0,
         "deadlock_ok": 1, "round_shape_ok": 1, "json_ok": 0.5, "fallback_rate": 0.5,
         "lines": 10, "calls": 7, "cost_usd": 0.001, "avg_latency_ms": 300, "persona": 1.0},
    ])
    assert agg["len_ok"] == 0.75 and agg["lines"] == 30 and agg["calls"] == 14, agg
    assert agg["persona"] == 1.5 and agg["avg_latency_ms"] == 200.0, agg
    assert agg["cost_usd"] == 0.002, agg
    # 一个 case 都没评审 → persona 必须是 None，不能是 0
    assert runner.aggregate([{"persona": None, "len_ok": 1.0}])["persona"] is None

    # 方向：旁白率升高是变坏，len_ok 升高是变好
    assert "差" in runner.delta("narration_rate", 0.2, 0.1)
    assert "好" in runner.delta("narration_rate", 0.1, 0.2)
    assert "好" in runner.delta("len_ok", 0.9, 0.8)
    assert "差" in runner.delta("len_ok", 0.8, 0.9)
    assert runner.delta("len_ok", 0.8, 0.8).strip() == "="
    assert runner.delta("len_ok", None, 0.8) == ""


def test_run_offline_end_to_end():
    rid = runner.main(["--offline", "--label", "selfcheck", "--cases", "quit-job", "--rounds", "2"])
    run = store.get_eval_run(rid)
    assert run["label"] == "selfcheck" and run["judge_model"] is None
    assert run["finished_at"] and len(run["cases"]) == 1
    assert run["metrics"]["fallback_rate"] == 1.0, "断了模型，兜底率必须是 100%"
    assert run["cases"][0]["case_id"] == "quit-job"
    assert isinstance(run["cases"][0]["failures"], list)
    assert store.get_eval_run(99999) is None


def main():
    store.init_db()   # judge_persona 失败时也要能写轨迹
    test_narration()
    test_perfect_session()
    test_each_failure_is_caught()
    test_determinism()
    test_judge_refuses_to_invent()
    test_sampling()
    test_aggregate_and_delta()
    assert len(caseset.CASES) == len(caseset.BY_ID), "case id 必须唯一"
    assert all(c["context"] for c in caseset.CASES), "每个 case 都要有背景，否则测不到文库检索"
    test_run_offline_end_to_end()
    print(f"eval OK · {len(caseset.CASES)} cases · 打分器确定性已验证")


if __name__ == "__main__":
    main()
