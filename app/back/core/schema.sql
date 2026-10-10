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

-- 蝴蝶文库：浣熊往里存"事实"，蝴蝶检索出来编织成自证的结论。
-- vec 是原始 float32 数组的字节；语料就这么大，全量算余弦比引入向量库便宜得多。
CREATE TABLE IF NOT EXISTS fact (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT,                              -- NULL = 跨朝会的公共文库
  text        TEXT NOT NULL,
  source      TEXT NOT NULL DEFAULT 'unknown',   -- petition | raccoon | user
  vec         BLOB,
  dim         INTEGER NOT NULL DEFAULT 0,
  vectorizer  TEXT NOT NULL DEFAULT '',          -- 模型名，或 hashing（离线兜底）
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_session ON fact (session_id);

-- 每次检索一行：命中了什么、分数多高、蝴蝶最后引用了几条。
-- 检索到的和真去引用的之间的差，就是"确认偏误"的可量化形式。
CREATE TABLE IF NOT EXISTS retrieval (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id  TEXT,
  turn_id     INTEGER,
  minister    TEXT,
  query       TEXT NOT NULL,
  vectorizer  TEXT NOT NULL DEFAULT '',
  corpus      INTEGER NOT NULL DEFAULT 0,        -- 检索时文库里有多少条
  hits        TEXT NOT NULL DEFAULT '[]',        -- JSON: [{fact_id, score, text}]
  top_score   REAL NOT NULL DEFAULT 0,
  cited       INTEGER NOT NULL DEFAULT 0,        -- 命中里被真正引用的条数
  latency_ms  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_session ON retrieval (session_id, id);

-- 评估回归：一次 run = 跑一遍固定议题集，打一组分。
-- 存下来才能回答"改了 prompt 之后变好还是变坏"，而不是靠感觉。
CREATE TABLE IF NOT EXISTS eval_run (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  label        TEXT NOT NULL DEFAULT '',
  model        TEXT NOT NULL DEFAULT '',
  judge_model  TEXT,                            -- NULL = 这次没跑人设评审
  cases        INTEGER NOT NULL DEFAULT 0,
  metrics      TEXT NOT NULL DEFAULT '{}',      -- JSON
  started_at   TEXT NOT NULL,
  finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS eval_case (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id     INTEGER NOT NULL REFERENCES eval_run(id),
  case_id    TEXT NOT NULL,
  topic      TEXT NOT NULL,
  session_id TEXT,
  metrics    TEXT NOT NULL DEFAULT '{}',        -- JSON
  failures   TEXT NOT NULL DEFAULT '[]',        -- JSON: [{kind, minister, text}]
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evalcase_run ON eval_case (run_id);
