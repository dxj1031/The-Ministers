"""OpenAI 兼容的模型调用，每一次调用都落一行 llm_trace。

监控台的所有数据都来自这里 —— 所以项目里任何地方调模型都必须走 complete()/embed()，
不要绕过去直接 httpx.post，否则那次调用在监控台上就是隐形的。
"""
import json
import os
import time

import httpx

from . import store

# MINISTERS_* 优先，这样 .env 可以指向本地 Ollama 而不用动全局的 OPENAI_API_KEY。
BASE_URL = (os.environ.get("MINISTERS_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1").rstrip("/")
API_KEY = os.environ.get("MINISTERS_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("MINISTERS_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.environ.get("MINISTERS_EMBED_MODEL", "text-embedding-3-small")
TIMEOUT = float(os.environ.get("MINISTERS_TIMEOUT", "30"))

# USD / 1M tokens，(输入, 输出)。前缀匹配，未知模型算 0 并在监控台显示 unpriced。
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


def price_of(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    key = max((k for k in PRICES if model.startswith(k)), key=len, default=None)
    if key is None:
        return 0.0
    pin, pout = PRICES[key]
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


class LLMError(RuntimeError):
    pass


def _post(path: str, payload: dict) -> dict:
    if not API_KEY:
        raise LLMError("OPENAI_API_KEY 未设置")
    r = httpx.post(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=TIMEOUT,
    )
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def complete(messages: list[dict], *, op: str, session_id: str | None = None,
             minister: str | None = None, model: str | None = None,
             temperature: float = 0.9, max_tokens: int = 400,
             as_json: bool = False, fallback: str | None = None) -> tuple[str, int]:
    """调模型并记录轨迹。返回 (文本, trace_id)。

    模型不可用时：若给了 fallback 就返回它并标记 fallback=1（原型仍然能跑，
    但监控台上兜底率是可见的，不会悄悄退化）；没给就抛 LLMError。
    """
    model = model or MODEL
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if as_json:
        payload["response_format"] = {"type": "json_object"}

    t0 = time.perf_counter()
    try:
        data = _post("/chat/completions", payload)
        ms = int((time.perf_counter() - t0) * 1000)
        text = data["choices"][0]["message"]["content"] or ""
        u = data.get("usage") or {}
        pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        tid = store.add_trace(op, model, session_id=session_id, minister=minister,
                              prompt_tokens=pt, completion_tokens=ct,
                              cost_usd=price_of(model, pt, ct), latency_ms=ms,
                              request=messages, response=text)
        return text, tid
    except Exception as e:  # 网络、鉴权、限流、响应结构变化都算一次失败调用
        ms = int((time.perf_counter() - t0) * 1000)
        tid = store.add_trace(op, model, session_id=session_id, minister=minister,
                              latency_ms=ms, ok=False, fallback=fallback is not None,
                              error=f"{type(e).__name__}: {e}"[:500],
                              request=messages, response=fallback)
        if fallback is None:
            raise
        return fallback, tid


def complete_json(messages: list[dict], *, fallback: dict, **kw) -> tuple[dict, int]:
    """要求模型返回 JSON 对象；解析失败也当作一次失败调用，回退到 fallback。"""
    text, tid = complete(messages, as_json=True,
                         fallback=json.dumps(fallback, ensure_ascii=False), **kw)
    try:
        out = json.loads(text)
        if not isinstance(out, dict):
            raise ValueError("不是 JSON 对象")
        return out, tid
    except Exception as e:
        # op 后缀 _parse：解析失败单独成一类，别和成功的调用混在一起被当成一次回合
        store.add_trace(kw.get("op", "call") + "_parse", kw.get("model") or MODEL,
                        session_id=kw.get("session_id"), minister=kw.get("minister"),
                        ok=False, fallback=True, error=f"JSON 解析失败: {e}"[:500],
                        response=text)
        return fallback, tid


def embed(texts: list[str], *, session_id: str | None = None,
          model: str | None = None) -> list[list[float]]:
    model = model or EMBED_MODEL
    t0 = time.perf_counter()
    try:
        data = _post("/embeddings", {"model": model, "input": texts})
        ms = int((time.perf_counter() - t0) * 1000)
        pt = (data.get("usage") or {}).get("prompt_tokens", 0)
        store.add_trace("embed", model, session_id=session_id, prompt_tokens=pt,
                        cost_usd=price_of(model, pt, 0), latency_ms=ms,
                        request={"n": len(texts)})
        return [d["embedding"] for d in data["data"]]
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        store.add_trace("embed", model, session_id=session_id, latency_ms=ms, ok=False,
                        error=f"{type(e).__name__}: {e}"[:500], request={"n": len(texts)})
        raise
