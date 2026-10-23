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
from app.back.evaluation import scorers  # noqa: E402

OUT = ROOT / "snapshot.json"
MAX_SESSIONS = 8          # 展示够用就行，别把整个库塞进仓库
MAX_TRACES = 40
MAX_EVAL_RUNS = 6
EVAL_SCAN = 40            # 先多捞一些，滤掉离线跑之后再取前 MAX_EVAL_RUNS 条


def main():
    sessions = store.list_sessions(MAX_SESSIONS)
    detail = {}
    for s in sessions:
        d = store.get_session(s["id"])
        d["traces"] = store.list_traces(s["id"], MAX_TRACES)
        d["retrievals"] = store.list_retrievals(s["id"])
        detail[s["id"]] = d

    # 评估 run 连同它的 case 明细一起内嵌，静态页不能再发第二个请求。
    #
    # 跳过 --offline 的跑：那是故意断开模型、只验打分链路的，兜底率必然是 100%。
    # 它们在本地是有用的回归，但放到线上展示会显示成六行「json_ok 0% / 兜底率 100%」，
    # 看着像整个系统是坏的 —— 那不是事实，是在拿自检冒充成绩。
    # 没跑完的那条也要跳过：metrics 还是空的，导出去就是一行没有数字的 run。
    scanned = store.list_eval_runs(EVAL_SCAN)
    picked = [r for r in scanned
              if r["finished_at"] and (r["metrics"] or {}).get("fallback_rate") != 1.0
              ][:MAX_EVAL_RUNS]
    evals = [store.get_eval_run(r["id"]) for r in picked]
    skipped = len(scanned) - len(picked)

    # 档案指标走和 /api/stats 同一个函数，静态页和实时页看到的是同一个判据
    # 总览也要排除离线跑：否则首页三张卡会写着「失败率 74% · 兜底率 53%」，
    # 而那 53% 全是我自己断开模型制造的。同一条规则，眼睛看得到的地方都得一致。
    rows = store.user_read_rows()
    stats = store.stats(store.offline_eval_sessions())
    stats["archive"] = dict(scorers.score_user_read(rows), rows=len(rows))

    snap = {
        "exported_at": store.now(),
        "health": {"ok": True, "db": "snapshot"},
        "stats": stats,
        "sessions": sessions,
        "evals": evals,
        "detail": detail,
    }
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"{OUT.name}: {len(sessions)} 场朝会 · {snap['stats']['calls']} 次调用 · "
          f"{len(evals)} 次评估（跳过 {skipped} 次离线跑） · {kb:.0f} KB")
    if kb > 800:
        print("提示：快照偏大，调小 MAX_SESSIONS / MAX_TRACES")


if __name__ == "__main__":
    main()
