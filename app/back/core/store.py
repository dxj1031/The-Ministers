"""SQLite 数据层：朝会、发言、LLM 调用轨迹。

ponytail: 直接写 SQL，不上 ORM —— 表就四张，而且这里的目的之一就是练真 SQL。
换 Postgres 的路径见 schema.sql 顶部注释。
"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _dotenv() -> None:
    """读根目录 .env。ponytail: 只为省一个 python-dotenv 依赖，已存在的环境变量优先。"""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_dotenv()  # 必须在下面读 MINISTERS_DB 之前，也在 llm.py 读 OPENAI_* 之前

DB_PATH = os.environ.get("MINISTERS_DB", str(ROOT / "data" / "ministers.db"))
SCHEMA = Path(__file__).with_name("schema.sql")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA.read_text(encoding="utf-8"))


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


# ---------- 朝会 ----------

def create_session(topic: str, context: str = "", lang: str = "zh") -> str:
    sid = uuid.uuid4().hex[:12]
    with conn() as c:
        c.execute(
            "INSERT INTO court_session (id, topic, context, lang, created_at) VALUES (?,?,?,?,?)",
            (sid, topic, context, lang, now()),
        )
    return sid


def set_lean(session_id: str, lean: float) -> None:
    with conn() as c:
        c.execute("UPDATE court_session SET lean=? WHERE id=?", (max(-1.0, min(1.0, lean)), session_id))


def end_session(session_id: str, verdict: str) -> None:
    with conn() as c:
        c.execute(
            "UPDATE court_session SET status='decided', verdict=?, ended_at=? WHERE id=?",
            (verdict, now(), session_id),
        )


def get_session(session_id: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM court_session WHERE id=?", (session_id,)).fetchone()
        if row is None:
            return None
        s = dict(row)
        s["turns"] = _rows(c.execute("SELECT * FROM turn WHERE session_id=? ORDER BY seq", (session_id,)))
        return s


def list_sessions(limit: int = 50) -> list[dict]:
    with conn() as c:
        return _rows(c.execute(
            """SELECT s.*,
                      (SELECT COUNT(*) FROM turn t WHERE t.session_id = s.id)          AS turns,
                      (SELECT COUNT(*) FROM llm_trace x WHERE x.session_id = s.id)     AS calls,
                      (SELECT COALESCE(SUM(cost_usd),0) FROM llm_trace x
                         WHERE x.session_id = s.id)                                    AS cost_usd
               FROM court_session s ORDER BY s.created_at DESC LIMIT ?""",
            (limit,),
        ))


# ---------- 发言 ----------

def add_turn(session_id: str, minister: str, kind: str, stance: str,
             text: str, influence: float = 0.0, target: str | None = None) -> int:
    with conn() as c:
        seq = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM turn WHERE session_id=?",
                        (session_id,)).fetchone()[0]
        cur = c.execute(
            """INSERT INTO turn (session_id, seq, minister, kind, stance, influence, text, target, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session_id, seq, minister, kind, stance, influence, text, target, now()),
        )
        return cur.lastrowid


def current_stances(session_id: str) -> dict[str, dict]:
    """每位大臣最新一次发言时的立场 —— 朝堂当前状态就是发言记录推出来的，不另存一份。"""
    with conn() as c:
        rows = _rows(c.execute(
            """SELECT t.minister, t.stance, t.influence, t.seq
                 FROM turn t
                 JOIN (SELECT minister, MAX(seq) AS m FROM turn WHERE session_id=? GROUP BY minister) x
                   ON x.minister = t.minister AND x.m = t.seq
                WHERE t.session_id=?""",
            (session_id, session_id),
        ))
    return {r["minister"]: r for r in rows}


# ---------- 拾荒的用户档案 ----------

READ_FIELDS = ("anxiety", "impulse", "stake", "deadline")


def add_user_read(session_id: str | None, source: str, fields: dict) -> None:
    """追加一次整理。source: raccoon（拾荒整理的）| user（用户自己改的）。"""
    vals = {f: (fields.get(f) or "").strip() for f in READ_FIELDS}
    with conn() as c:
        c.execute(
            "INSERT INTO user_read (session_id, source, anxiety, impulse, stake, deadline, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (session_id, source, vals["anxiety"], vals["impulse"],
             vals["stake"], vals["deadline"], now()),
        )


def user_read() -> dict[str, dict]:
    """当前这份档案：每个字段各自取最新一条非空的，连同它是谁写的。

    按字段合并而不是整行取最新 —— 用户只改了「怕什么」，不该把拾荒整理的另外三项抹掉。
    空字符串当成「这次没说」，继续往前找：所以清空一个字段不会留下空洞，
    会露出上一次的答案。想否认一件事，写一句否认，别清空。
    """
    with conn() as c:
        rows = _rows(c.execute(
            "SELECT * FROM user_read ORDER BY id DESC LIMIT 200"))
    out: dict[str, dict] = {}
    for r in rows:
        for f in READ_FIELDS:
            if f not in out and (r[f] or "").strip():
                out[f] = {"text": r[f].strip(), "source": r["source"]}
    return out


# ---------- LLM 轨迹 ----------

def add_trace(op: str, model: str, *, session_id: str | None = None, turn_id: int | None = None,
              minister: str | None = None, prompt_tokens: int = 0, completion_tokens: int = 0,
              cost_usd: float = 0.0, latency_ms: int = 0, ok: bool = True, fallback: bool = False,
              error: str | None = None, request=None, response: str | None = None) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO llm_trace (session_id, turn_id, op, minister, model, prompt_tokens,
                                      completion_tokens, cost_usd, latency_ms, ok, fallback,
                                      error, request, response, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, turn_id, op, minister, model, prompt_tokens, completion_tokens,
             cost_usd, latency_ms, int(ok), int(fallback), error,
             json.dumps(request, ensure_ascii=False) if request is not None else None,
             response, now()),
        )
        return cur.lastrowid


def count_traces(session_id: str, op: str) -> int:
    """回合数只能按模型调用次数算 —— 按发言条数算的话，模型少写一句就少算一轮。"""
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM llm_trace WHERE session_id=? AND op=?",
                         (session_id, op)).fetchone()[0]


def list_traces(session_id: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM llm_trace"
    args: list = []
    if session_id:
        sql += " WHERE session_id=?"
        args.append(session_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        return _rows(c.execute(sql, args))


# ---------- 蝴蝶文库 ----------

def add_fact(text: str, *, source: str = "unknown", session_id: str | None = None,
             vec: bytes | None = None, dim: int = 0, vectorizer: str = "") -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO fact (session_id, text, source, vec, dim, vectorizer, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (session_id, text.strip(), source, vec, dim, vectorizer, now()),
        )
        return cur.lastrowid


def fact_exists(session_id: str | None, text: str) -> bool:
    sql = "SELECT 1 FROM fact WHERE text=? AND session_id IS ?"
    with conn() as c:
        return c.execute(sql, (text.strip(), session_id)).fetchone() is not None


def list_facts(session_id: str | None = None) -> list[dict]:
    """本局的事实 + 公共文库（session_id IS NULL）。"""
    with conn() as c:
        return _rows(c.execute(
            "SELECT * FROM fact WHERE session_id IS NULL OR session_id = ? ORDER BY id",
            (session_id,),
        ))


def add_retrieval(query: str, *, session_id: str | None = None, turn_id: int | None = None,
                  minister: str | None = None, vectorizer: str = "", corpus: int = 0,
                  hits: list | None = None, top_score: float = 0.0,
                  latency_ms: int = 0) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO retrieval (session_id, turn_id, minister, query, vectorizer,
                                      corpus, hits, top_score, cited, latency_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
            (session_id, turn_id, minister, query, vectorizer, corpus,
             json.dumps(hits or [], ensure_ascii=False), top_score, latency_ms, now()),
        )
        return cur.lastrowid


def set_last_cited(session_id: str, cited: int) -> None:
    with conn() as c:
        c.execute("""UPDATE retrieval SET cited=? WHERE id =
                     (SELECT MAX(id) FROM retrieval WHERE session_id=?)""",
                  (cited, session_id))


def list_retrievals(session_id: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM retrieval"
    args: list = []
    if session_id:
        sql += " WHERE session_id=?"
        args.append(session_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        rows = _rows(c.execute(sql, args))
    for r in rows:
        r["hits"] = json.loads(r["hits"])
    return rows


# ---------- 评估回归 ----------

def start_eval_run(label: str, model: str, judge_model: str | None, cases: int) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO eval_run (label, model, judge_model, cases, started_at)
               VALUES (?,?,?,?,?)""",
            (label, model, judge_model, cases, now()),
        )
        return cur.lastrowid


def finish_eval_run(run_id: int, metrics: dict) -> None:
    with conn() as c:
        c.execute("UPDATE eval_run SET metrics=?, finished_at=? WHERE id=?",
                  (json.dumps(metrics, ensure_ascii=False), now(), run_id))


def add_eval_case(run_id: int, case_id: str, topic: str, session_id: str | None,
                  metrics: dict, failures: list) -> int:
    with conn() as c:
        cur = c.execute(
            """INSERT INTO eval_case (run_id, case_id, topic, session_id, metrics,
                                      failures, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (run_id, case_id, topic, session_id,
             json.dumps(metrics, ensure_ascii=False),
             json.dumps(failures, ensure_ascii=False), now()),
        )
        return cur.lastrowid


def _ms_between(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 0
    try:
        return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() * 1000)
    except ValueError:
        return 0


def list_eval_runs(limit: int = 10) -> list[dict]:
    """最新的在前。metrics 解成 dict，duration_ms 顺手算好，省得前端自己算时间差。"""
    with conn() as c:
        rows = _rows(c.execute(
            "SELECT * FROM eval_run ORDER BY id DESC LIMIT ?", (limit,)))
    for r in rows:
        r["metrics"] = json.loads(r["metrics"] or "{}")
        r["duration_ms"] = _ms_between(r["started_at"], r["finished_at"])
    return rows


def get_eval_run(run_id: int) -> dict | None:
    runs = [r for r in list_eval_runs(1000) if r["id"] == run_id]
    if not runs:
        return None
    run = runs[0]
    with conn() as c:
        cs = _rows(c.execute(
            "SELECT * FROM eval_case WHERE run_id=? ORDER BY id", (run_id,)))
    for x in cs:
        x["metrics"] = json.loads(x["metrics"] or "{}")
        x["failures"] = json.loads(x["failures"] or "[]")
    run["cases"] = cs
    return run


def stats() -> dict:
    """监控台顶部指标。"""
    with conn() as c:
        total = dict(c.execute(
            """SELECT COUNT(*)                              AS calls,
                      COALESCE(SUM(prompt_tokens), 0)       AS prompt_tokens,
                      COALESCE(SUM(completion_tokens), 0)   AS completion_tokens,
                      COALESCE(SUM(cost_usd), 0)            AS cost_usd,
                      COALESCE(AVG(latency_ms), 0)          AS avg_latency_ms,
                      COALESCE(SUM(1 - ok), 0)              AS errors,
                      COALESCE(SUM(fallback), 0)            AS fallbacks
               FROM llm_trace"""
        ).fetchone())
        total["sessions"] = c.execute("SELECT COUNT(*) FROM court_session").fetchone()[0]
        total["by_op"] = _rows(c.execute(
            """SELECT op, COUNT(*) AS calls, COALESCE(AVG(latency_ms),0) AS avg_latency_ms,
                      COALESCE(SUM(cost_usd),0) AS cost_usd, COALESCE(SUM(1-ok),0) AS errors
               FROM llm_trace GROUP BY op ORDER BY calls DESC"""
        ))
        # p95 延迟：小表直接排序取分位，够用。
        lat = [r[0] for r in c.execute("SELECT latency_ms FROM llm_trace ORDER BY latency_ms").fetchall()]
        total["p95_latency_ms"] = lat[min(len(lat) - 1, int(len(lat) * 0.95))] if lat else 0
        total["rag"] = dict(c.execute(
            """SELECT COUNT(*)                                    AS searches,
                      COALESCE(SUM(CASE WHEN top_score > 0 THEN 1 ELSE 0 END), 0) AS with_hits,
                      COALESCE(AVG(top_score), 0)                 AS avg_top_score,
                      COALESCE(AVG(latency_ms), 0)                AS avg_latency_ms,
                      COALESCE(SUM(json_array_length(hits)), 0)   AS retrieved,
                      COALESCE(SUM(cited), 0)                     AS cited
               FROM retrieval"""
        ).fetchone())
        total["rag"]["facts"] = c.execute("SELECT COUNT(*) FROM fact").fetchone()[0]
        total["rag"]["vectorizers"] = _rows(c.execute(
            "SELECT vectorizer, COUNT(*) AS n FROM fact GROUP BY vectorizer ORDER BY n DESC"))
        return total
