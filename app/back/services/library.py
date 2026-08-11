"""蝴蝶文库：向量检索。

玩法上这是「确认偏误」—— 浣熊往文库里塞事实，蝴蝶检索出来，只挑支持自己结论的引用。
工程上这就是一条最小 RAG 链路：切句 → 向量化 → 余弦检索 → 塞进 prompt → 记录命中与引用。

向量来源可插拔：
  - 有 embedding API（llm.embed）就用真 embedding；
  - 没有就退回本地哈希向量（字符 n-gram → 定长稀疏向量，思路同 sklearn HashingVectorizer）。
两条路的检索数学完全一样，只有向量怎么来不同；用的哪一种会记进 retrieval.vectorizer，
所以监控台上看得见这次检索到底是不是真 embedding —— 不会糊弄过去。
"""
import hashlib
import json
import re
import time

import numpy as np

from ..core import llm, store

DIM = 512           # 哈希向量维度；语料是几十条，512 维足够拉开距离
TOP_K = 3
MIN_LEN = 6         # 太短的句子不入库，检索时只会制造噪音


# ---------- 向量化 ----------

def _ngrams(text: str, n: int = 2) -> list[str]:
    """中文按字 bigram，英文按词 —— 中英文混排的议题两种都会出现。"""
    t = re.sub(r"\s+", " ", text.lower()).strip()
    grams = [t[i:i + n] for i in range(max(0, len(t) - n + 1))]
    grams += re.findall(r"[a-z0-9]{2,}", t)
    return grams


def hash_vector(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for g in _ngrams(text):
        h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16)
        v[h % DIM] += 1.0 if h & 0x100 else -1.0     # 带符号，减少哈希碰撞的系统性偏差
    return _unit(v)


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def vectorize(texts: list[str], session_id: str | None = None) -> tuple[np.ndarray, str]:
    """返回 (矩阵, 向量化器名)。embedding 拿不到就退回哈希向量，不抛错。"""
    try:
        vecs = llm.embed(texts, session_id=session_id)
        return np.array([_unit(np.array(v, dtype=np.float32)) for v in vecs]), llm.EMBED_MODEL
    except Exception:
        return np.array([hash_vector(t) for t in texts], dtype=np.float32), "hashing"


# ---------- 入库 ----------

def split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？；\n]|(?<=[.!?])\s+", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= MIN_LEN]


def add_facts(texts: list[str], *, session_id: str | None = None,
              source: str = "unknown") -> int:
    """存一批事实。返回真正入库的条数（去重后）。"""
    fresh = [t for t in dict.fromkeys(texts) if len(t.strip()) >= MIN_LEN
             and not store.fact_exists(session_id, t.strip())]
    if not fresh:
        return 0
    mat, vec_name = vectorize(fresh, session_id)
    for text, v in zip(fresh, mat):
        store.add_fact(text, source=source, session_id=session_id,
                       vec=v.astype(np.float32).tobytes(), dim=len(v), vectorizer=vec_name)
    return len(fresh)


# ---------- 检索 ----------

def search(query: str, *, session_id: str | None = None, k: int = TOP_K,
           minister: str | None = None) -> list[dict]:
    """余弦 top-k。查询用和语料同一种向量化器，否则两边不在一个空间里。"""
    t0 = time.perf_counter()
    rows = store.list_facts(session_id)
    if not rows:
        store.add_retrieval(query, session_id=session_id, minister=minister, corpus=0,
                            latency_ms=int((time.perf_counter() - t0) * 1000))
        return []

    # 语料可能是分两次入库的（先真 embedding 后掉线退回哈希），只留占多数的那一种，
    # 否则维度和空间都对不上，算出来的"相似度"是假的。
    names = [r["vectorizer"] for r in rows]
    vec_name = max(set(names), key=names.count)
    rows = [r for r in rows if r["vectorizer"] == vec_name and r["vec"]]
    if not rows:
        return []

    if vec_name == "hashing":
        q = hash_vector(query)
    else:
        try:
            q = _unit(np.array(llm.embed([query], session_id=session_id)[0], dtype=np.float32))
        except Exception:
            q = None
        if q is None or len(q) != rows[0]["dim"]:
            # embedding 掉线：语料是真 embedding，查询却只能哈希 —— 不在一个空间，宁可不检索
            store.add_retrieval(query, session_id=session_id, minister=minister,
                                vectorizer="mismatch", corpus=len(rows),
                                latency_ms=int((time.perf_counter() - t0) * 1000))
            return []

    mat = np.array([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
    scores = mat @ q
    order = np.argsort(-scores)[:k]
    hits = [{"fact_id": rows[i]["id"], "score": round(float(scores[i]), 4),
             "text": rows[i]["text"], "source": rows[i]["source"]} for i in order
            if scores[i] > 0.05]

    store.add_retrieval(query, session_id=session_id, minister=minister, vectorizer=vec_name,
                        corpus=len(rows), hits=hits,
                        top_score=hits[0]["score"] if hits else 0.0,
                        latency_ms=int((time.perf_counter() - t0) * 1000))
    return hits


def count_cited(hits: list[dict], said: str) -> int:
    """蝴蝶实际引用了几条 —— 检索到 N 条却只用支持自己的那几条，就是确认偏误本身。

    判定用字符 bigram 重合度，模型会改写措辞，不能指望原样复述。
    """
    if not said:
        return 0
    said_grams = set(_ngrams(said))
    n = 0
    for h in hits:
        g = set(_ngrams(h["text"]))
        if g and len(g & said_grams) / len(g) >= 0.3:
            n += 1
    return n


def mark_cited(session_id: str, hits: list[dict], said: str) -> int:
    n = count_cited(hits, said)
    store.set_last_cited(session_id, n)
    return n
