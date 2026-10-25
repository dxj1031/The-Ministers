"""Public search, evidence provenance and topic isolation without external calls."""
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / f"research-test-{uuid.uuid4().hex}.db"
os.environ["MINISTERS_DB"] = str(DB)
os.environ["MINISTERS_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

import httpx
from fastapi.testclient import TestClient
from app.back.core import store
from app.back.services import court, research
from app.back.main import app


def main():
    store.init_db()
    assert not research.relevant("starting a PhD at 30", "STARTING dictionary definition")
    assert not research.relevant("PhD 30", "300 PhD students")
    assert research.relevant("starting a PhD at 30", "I started a PhD at 30 and worried about funding")
    response = httpx.Response(200, request=httpx.Request("GET", "https://www.bing.com/search"),
        content=b'<rss><channel><item><title>Starting a PhD at 30</title>'
                b'<description>PhD at 30: I feared the opportunity cost.</description>'
                b'<link>https://news.ycombinator.com/item?id=123</link></item>'
                b'<item><title>Starting definition</title><description>Dictionary entry</description>'
                b'<link>https://example.org/dictionary</link></item></channel></rss>')
    with patch.dict(os.environ, {"MINISTERS_SEARCH_API_KEY": ""}), patch.object(research.httpx, "get", return_value=response):
        query, hits = research.public_reactions("starting a PhD at 30", "fox")
        assert len(hits) == 1 and hits[0]["url"] == "https://news.ycombinator.com/item?id=123"
        assert "fear" in query
    empty = httpx.Response(200, request=httpx.Request("GET", "https://www.bing.com/search"),
                           content=b"<rss><channel/></rss>")
    comments = httpx.Response(200, request=httpx.Request("GET", "https://hn.algolia.com/api/v1/search"),
                              json={"hits": [{"comment_text": "<p>I began a PhD at 30; I feared the cost.</p>",
                                                "objectID": "123", "story_title": "Graduate study"}]})
    with patch.dict(os.environ, {"MINISTERS_SEARCH_API_KEY": ""}), patch.object(research.httpx, "get", side_effect=[empty, comments]):
        fallback_query, fallback_hits = research.public_reactions("A PhD at 30 — brave or fleeing?", "fox")
        assert "Hacker News" in fallback_query and fallback_hits[0]["url"].endswith("id=123")
        assert "<p>" not in fallback_hits[0]["text"]
    dedicated = httpx.Response(200, request=httpx.Request("POST", "https://api.tavily.com/search"),
                               json={"results": [{"title": "PhD at 30", "content": "PhD at 30 funding experience",
                                                   "url": "https://example.org/funding"}]})
    with patch.dict(os.environ, {"MINISTERS_SEARCH_API_KEY": "test-key"}), patch.object(research.httpx, "post", return_value=dedicated) as search:
        _, dedicated_hits = research.public_reactions("PhD at 30", "collie")
        assert dedicated_hits and search.call_args.kwargs["json"]["max_results"] == 5

    with patch.dict(os.environ, {"MINISTERS_ACCESS_KEY": "", "RENDER": ""}), TestClient(app) as client:
        result = client.post("/api/library", json={"title": "PhD notes", "text": "PhD at 30 has a funding limit of four years."})
        assert result.status_code == 200 and result.json()["added"] == 1
        assert client.post("/api/library", json={"title": "PhD notes", "text": "PhD at 30 has a funding limit of four years."}).json()["added"] == 0

    sid = store.create_session("starting a PhD at 30")
    session = store.get_session(sid)
    def lookup(topic, minister):
        assert topic == session["topic"]
        return topic, hits
    with patch.dict(os.environ, {"MINISTERS_WEB_RESEARCH": "1"}), patch.object(research, "public_reactions", side_effect=lookup) as tool:
        research.prepare(session)
        assert tool.call_count == 12
        research.prepare(session)
        assert tool.call_count == 12, "Do not repeat the same public lookup every turn"
    sources = research.sources(session, ["fox"])
    public = {k: v for k, v in sources.items() if v["kind"] == "public_reaction"}
    assert len(public) == 1
    key = next(iter(public))
    arg = court._argument({"reason": "This reaction fears lost income", "source": key}, sources)
    assert arg["source_url"] == "https://news.ycombinator.com/item?id=123"
    assert arg["basis"] == "public_reaction"
    for ref in (f"[{key}]", f"材料编号：{key}", [key]):
        assert court._argument({"reason": "This reaction fears lost income", "source": ref}, sources)["source_url"] == arg["source_url"]
    assert any(v["kind"] == "user_library" for v in sources.values())
    other = store.get_session(store.create_session("unrelated new topic"))
    assert not any(v["kind"] == "public_reaction" for v in research.sources(other, ["fox"]).values())

    stale = store.create_session("open a cat cafe")
    store.add_user_read(stale, "raccoon", {"impulse": "open a cat cafe"})
    assert "cat cafe" not in court._private_block(["rabbit"], "en", sid)
    assert "cat cafe" not in str(court.snapshot(sid)["mind"])
    shared = store.get_session(store.create_session("见家长要不要坦白纹身"))
    with patch.dict(os.environ, {"MINISTERS_WEB_RESEARCH": "1"}), patch.object(research.llm, "search_public", return_value=[{
            "url": "https://example.org/tattoo", "title": "Parents and tattoos", "text": "公开讨论中有人担忧长辈对纹身的看法。"}]), \
            patch.object(research, "public_reactions") as legacy:
        research.prepare(shared)
        legacy.assert_not_called()
    for mid in research.ANGLES:
        assert any(v.get("url") == "https://example.org/tattoo" for v in research.sources(shared, [mid]).values())
    assert court.snapshot(shared["id"])["research"][0]["hits"] == 1
    grounded = httpx.Response(200, request=httpx.Request("POST", "https://generativelanguage.googleapis.com/test"), json={
        "candidates": [{"content": {"parts": [{"text": "An uncited invented claim must not become evidence."}]},
                        "groundingMetadata": {"webSearchQueries": ["parents tattoos discussion"],
                          "groundingChunks": [{"web": {"title": "Public discussion", "uri": "https://example.org/actual"}},
                                              {"web": {"title": "Uncited", "uri": "https://example.org/uncited"}}],
                          "groundingSupports": [{"segment": {"text": "Some participants worry about family expectations."}, "groundingChunkIndices": [0, 99]}]}}]})
    with patch.object(research.llm, "BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"), \
            patch.object(research.llm, "API_KEY", "test-key"), patch.object(research.llm.httpx, "post", return_value=grounded) as native:
        native_hits = research.llm.search_public(shared["topic"], session_id=shared["id"])
        assert len(native_hits) == 1 and native_hits[0]["url"] == "https://example.org/actual"
        assert "uncited" not in native_hits[0]["text"]
        assert native.call_args.kwargs["json"]["tools"] == [{"type": "google_search"}]
        assert store.list_traces(shared["id"])[-1]["op"] == "research"
    cited_text = "部分公开讨论者担心家庭期待与经济成本。"
    interactions = httpx.Response(200, request=httpx.Request("POST", "https://generativelanguage.googleapis.com/test"), json={
        "steps": [{"type": "google_search_call", "arguments": {"queries": ["parents tattoos"]}},
                  {"type": "model_output", "content": [{"type": "text", "text": cited_text,
                    "annotations": [{"type": "url_citation", "url": "https://example.org/cited", "title": "Discussion",
                                     "start_index": 0, "end_index": len(cited_text.encode('utf-8'))}]}]}]})
    with patch.object(research.llm, "BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"), \
            patch.object(research.llm, "API_KEY", "test-key"), patch.object(research.llm.httpx, "post", return_value=interactions):
        assert research.llm.search_public(shared["topic"], session_id=shared["id"])[0]["text"] == cited_text
    failed = store.get_session(store.create_session("PhD at 30"))
    with patch.dict(os.environ, {"MINISTERS_WEB_RESEARCH": "1"}), patch.object(research, "public_reactions", side_effect=httpx.ConnectError("offline")):
        research.prepare(failed)
    assert all(r["vectorizer"] == "web_unavailable" for r in store.list_retrievals(failed["id"]))
    print("research OK: real HTTP parsing, relevance, all ministers, caching, import, citations, isolation, failures")


if __name__ == "__main__":
    try:
        main()
    finally:
        DB.unlink(missing_ok=True)
