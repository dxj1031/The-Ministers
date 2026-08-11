-- The Ministers 数据层
-- ponytail: 故意写成可移植 SQL（没有 sqlite 专属语法），
-- 以后换 Postgres 只要把 store.py 的 sqlite3 换成 psycopg、把 ? 换成 %s。

CREATE TABLE IF NOT EXISTS court_session (
  id          TEXT PRIMARY KEY,
  topic       TEXT NOT NULL,
  context     TEXT NOT NULL DEFAULT '',
  lang        TEXT NOT NULL DEFAULT 'zh',
  status      TEXT NOT NULL DEFAULT 'debating',   -- debating | recess | decided
  verdict     TEXT,                               -- approve | reject | shelve | adjourn
  lean        REAL NOT NULL DEFAULT 0,            -- 皇帝倾向 -1..1
  created_at  TEXT NOT NULL,
  ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS turn (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT NOT NULL REFERENCES court_session(id),
  seq         INTEGER NOT NULL,
  minister    TEXT NOT NULL,
  kind        TEXT NOT NULL,                      -- opening | rebuttal | lobby | decree | verdict
  stance      TEXT NOT NULL,                      -- pro | con | undecided
  influence   REAL NOT NULL DEFAULT 0,
  text        TEXT NOT NULL,
  target      TEXT,                               -- 游说对象
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turn_session ON turn (session_id, seq);

-- 每一次 LLM 调用一行。监控台完全建立在这张表上。
CREATE TABLE IF NOT EXISTS llm_trace (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id        TEXT,
  turn_id           INTEGER,
  op                TEXT NOT NULL,                -- stance | speak | lobby | verdict | embed | chat
  minister          TEXT,
  model             TEXT NOT NULL,
  prompt_tokens     INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd          REAL NOT NULL DEFAULT 0,
  latency_ms        INTEGER NOT NULL DEFAULT 0,
  ok                INTEGER NOT NULL DEFAULT 1,
  fallback          INTEGER NOT NULL DEFAULT 0,   -- 走了本地兜底而不是模型
  error             TEXT,
  request           TEXT,                         -- JSON: 发出去的 messages
  response          TEXT,                         -- 模型原始文本
  created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trace_session ON llm_trace (session_id, id);
CREATE INDEX IF NOT EXISTS idx_trace_created ON llm_trace (created_at);
