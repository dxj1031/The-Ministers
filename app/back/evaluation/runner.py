"""评估回归：跑一遍固定议题集，打分，存库，和上一次对比。

    python -m app.back.evaluation.runner --label baseline
    python -m app.back.evaluation.runner --label after-prompt-fix --judge
    python -m app.back.evaluation.runner --cases quit-job,confess --rounds 2
    python -m app.back.evaluation.runner --offline --label harness   # 不调模型，只验证打分链路

每次 run 存成一行，所以「改完 prompt 是变好还是变坏」有据可查，不靠感觉。
机械指标是确定性的；人设贴合度（--judge）由 LLM 评审打分，有方差，单独列。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.back.core import llm, store                     # noqa: E402
from app.back.evaluation import cases as caseset         # noqa: E402
from app.back.evaluation import scorers                  # noqa: E402
from app.back.services import court                      # noqa: E402

# 越低越好的指标，报表里要反着标颜色
LOWER_BETTER = {"fallback_rate", "narration_rate", "dup_rate"}
RATIOS = ["json_ok", "fallback_rate", "len_ok", "narration_rate", "dup_rate",
          "stance_spread_ok", "deadlock_ok", "round_shape_ok"]


def run_case(case: dict, rounds: int, judge: bool) -> tuple[dict, list[dict], str]:
    snap = court.open_court(case["topic"], case["context"], case.get("lang", "zh"))
    sid = snap["id"]
    for _ in range(rounds):
        snap = court.next_round(sid)
    snap = court.verdict(sid, "shelve")

    metrics, failures = scorers.score_case(snap["turns"], snap["tally"], snap["round"])

    # JSON 合法率与兜底率从调用轨迹里来，不是重新判一遍模型输出 ——
    # llm.py 已经在失败时写了 ok=0 / fallback=1，评估只负责汇总，单一事实来源。
    traces = store.list_traces(sid, 200)
    gen = [t for t in traces if t["op"] in ("stance", "speak", "verdict")]
    parse_fail = sum(1 for t in traces if t["op"].endswith("_parse"))
    n = len(gen) or 1
    metrics["calls"] = len(gen)
    metrics["json_ok"] = round(1 - (parse_fail + sum(1 for t in gen if not t["ok"])) / n, 4)
    metrics["fallback_rate"] = round(sum(1 for t in gen if t["fallback"]) / n, 4)
    metrics["cost_usd"] = round(sum(t["cost_usd"] for t in traces), 6)
    metrics["avg_latency_ms"] = round(sum(t["latency_ms"] for t in gen) / n, 1)

    if judge:
        score, bad = scorers.judge_persona(scorers.sample_lines(snap["turns"]), session_id=sid)
        metrics["persona"] = score
        failures += bad
    else:
        metrics["persona"] = None
    return metrics, failures, sid


def aggregate(per_case: list[dict]) -> dict:
    """case 层取平均；比例类四舍五入到四位，计数类求和。"""
    if not per_case:
        return {}
    out: dict = {}
    for k in RATIOS:
        vals = [m[k] for m in per_case if m.get(k) is not None]
        out[k] = round(sum(vals) / len(vals), 4) if vals else None
    for k in ("lines", "calls"):
        out[k] = sum(m.get(k, 0) for m in per_case)
    out["cost_usd"] = round(sum(m.get("cost_usd", 0) for m in per_case), 6)
    lat = [m["avg_latency_ms"] for m in per_case if m.get("avg_latency_ms")]
    out["avg_latency_ms"] = round(sum(lat) / len(lat), 1) if lat else 0
    persona = [m["persona"] for m in per_case if m.get("persona") is not None]
    out["persona"] = round(sum(persona) / len(persona), 4) if persona else None
    return out


def fmt(k: str, v) -> str:
    if v is None:
        return "—"
    if k in RATIOS:
        return f"{v * 100:.1f}%"
    if k == "persona":
        return f"{v:.2f}/2"
    if k == "cost_usd":
        return f"${v:.5f}"
    if k == "avg_latency_ms":
        return f"{v:.0f}ms"
    return str(v)


def delta(k: str, now, prev) -> str:
    if now is None or prev is None or k in ("lines", "calls", "cost_usd"):
        return ""
    d = now - prev
    if abs(d) < 1e-9:
        return "  ="
    better = (d < 0) if k in LOWER_BETTER else (d > 0)
    arrow = "↑" if d > 0 else "↓"
    unit = f"{abs(d) * 100:.1f}pp" if k in RATIOS else f"{abs(d):.2f}"
    return f"  {arrow}{unit} {'好' if better else '差'}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="The Ministers 评估回归")
    ap.add_argument("--label", default="", help="给这次 run 起个名字，比如 after-prompt-fix")
    ap.add_argument("--cases", default="", help="只跑这些 case id，逗号分隔")
    ap.add_argument("--rounds", type=int, default=court.ROUNDS_PER_SESSION)
    ap.add_argument("--judge", action="store_true", help="额外用 LLM 评审人设贴合度（会多花调用）")
    ap.add_argument("--offline", action="store_true", help="断开模型，只验证打分链路是否能跑通")
    a = ap.parse_args(argv)

    if a.offline:
        os.environ["MINISTERS_API_KEY"] = ""
        os.environ["OPENAI_API_KEY"] = ""
        llm.API_KEY = ""

    picked = [caseset.BY_ID[c] for c in a.cases.split(",") if c in caseset.BY_ID] \
        if a.cases else caseset.CASES
    if not picked:
        sys.exit("没有匹配的 case id。可用：" + ", ".join(caseset.BY_ID))

    store.init_db()
    run_id = store.start_eval_run(a.label, llm.MODEL,
                                  llm.MODEL if a.judge else None, len(picked))
    print(f"run #{run_id} · {len(picked)} cases · {llm.MODEL}"
          f"{' · judge on' if a.judge else ''}{' · offline' if a.offline else ''}\n")

    t0 = time.perf_counter()
    per_case = []
    for i, case in enumerate(picked, 1):
        c0 = time.perf_counter()
        metrics, failures, sid = run_case(case, a.rounds, a.judge)
        store.add_eval_case(run_id, case["id"], case["topic"], sid, metrics, failures)
        per_case.append(metrics)
        print(f"[{i}/{len(picked)}] {case['id']:<13} "
              f"{int((time.perf_counter() - c0))}s  "
              f"len_ok {fmt('len_ok', metrics['len_ok'])}  "
              f"旁白 {fmt('narration_rate', metrics['narration_rate'])}  "
              f"重复 {fmt('dup_rate', metrics['dup_rate'])}  "
              f"人设 {fmt('persona', metrics['persona'])}  "
              f"失败 {len(failures)}", flush=True)

    total = aggregate(per_case)
    store.finish_eval_run(run_id, total)
    prev = next((r for r in store.list_eval_runs(5) if r["id"] != run_id), None)

    print(f"\nrun #{run_id} 汇总  ({int(time.perf_counter() - t0)}s)"
          + (f"   对比 run #{prev['id']} {prev['label'] or ''}" if prev else "   （首次 run，无对比）"))
    for k in RATIOS + ["persona", "lines", "calls", "avg_latency_ms", "cost_usd"]:
        d = delta(k, total.get(k), (prev or {}).get("metrics", {}).get(k)) if prev else ""
        print(f"  {k:<17} {fmt(k, total.get(k)):>9}{d}")
    return run_id


if __name__ == "__main__":
    main()
