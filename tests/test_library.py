"""蝴蝶文库自检：python tests/test_library.py

关掉 embedding API，验证离线哈希向量这条路能完整跑通检索。
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
from app.back.services import library  # noqa: E402


def main():
    store.init_db()

    # 语料为空时不能炸，而且也要留一行痕迹（说明检索发生过，只是没东西可查）
    empty = store.create_session("空文库")
    assert library.search("随便查", session_id=empty) == []
    assert store.list_retrievals(empty)[0]["corpus"] == 0

    sid = store.create_session("要不要辞职去开一家猫咖")

    # 切句：句号分隔，太短的丢掉
    sents = library.split_sentences("存款够撑八个月。房东明年涨租。好。同事说猫咖回本要两年")
    assert sents == ["存款够撑八个月", "房东明年涨租", "同事说猫咖回本要两年"], sents

    n = library.add_facts(sents, session_id=sid, source="petition")
    assert n == 3, n
    assert library.add_facts(sents, session_id=sid) == 0, "重复入库必须被去重"

    facts = store.list_facts(sid)
    assert len(facts) == 3 and all(f["vectorizer"] == "hashing" for f in facts), facts
    assert all(f["dim"] == library.DIM for f in facts)

    # 检索：查房租，第一条必须是房租那句，不能是回本那句
    hits = library.search("房东涨租怎么办", session_id=sid)
    assert hits, "应该有命中"
    assert hits[0]["text"] == "房东明年涨租", hits
    assert 0 < hits[0]["score"] <= 1.0001, hits[0]["score"]
    assert len(hits) <= library.TOP_K

    # 别的朝会看不到这局的事实
    other = store.create_session("别的议题")
    assert library.search("房东涨租怎么办", session_id=other) == []

    # 公共文库（session_id=None）对所有朝会可见
    library.add_facts(["猫毛过敏的客人会投诉"], source="user")
    assert any(h["text"] == "猫毛过敏的客人会投诉"
               for h in library.search("过敏投诉", session_id=other)), "公共文库应该跨朝会可见"

    # 引用判定：改写过也要算引用，完全无关的不算
    assert library.count_cited(hits, "房东明年就要涨租了，臣早有记录") >= 1
    assert library.count_cited(hits, "香蕉滑一个！") == 0

    # 每次检索都要留痕，且记下用的哪种向量化器
    rs = store.list_retrievals(sid)
    assert len(rs) >= 1 and rs[0]["vectorizer"] == "hashing", rs[0]
    assert rs[0]["corpus"] == 3, rs[0]
    assert isinstance(rs[0]["hits"], list) and rs[0]["hits"], rs[0]

    library.mark_cited(sid, hits, "房东明年就要涨租了")
    assert store.list_retrievals(sid)[0]["cited"] >= 1

    rag = store.stats()["rag"]
    assert rag["facts"] == 4 and rag["searches"] >= 3, rag
    assert rag["cited"] >= 1, rag

    print(f"library OK · {rag['facts']} facts · {rag['searches']} searches · "
          f"top={hits[0]['score']} · cited={rag['cited']}/{rag['retrieved']}")


if __name__ == "__main__":
    main()
