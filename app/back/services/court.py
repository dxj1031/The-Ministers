"""朝堂辩论引擎。

规则由代码定死（谁能对呛、谁会倒戈、死锁上限），模型只负责把具体议题填进这些槽位。
这样换模型、模型挂掉、模型胡说都不会让玩法崩掉 —— 见 README「角色先于模型」。

每回合恰好一次模型调用，落一行 llm_trace。
"""
import hashlib
import json

from ..core import llm, store
from ..ministers import roster
from . import library

STANCES = ("pro", "con", "undecided")
LANG_RULE = {"zh": "所有台词用中文。", "en": "Write every line of dialogue in English."}
MAX_UNDECIDED = 3          # 未定超过这个数就强制站队，避免朝堂总停在「都可以」
ROUNDS_PER_SESSION = 5


# ---------- 无模型时的兜底：按议题哈希产生稳定立场 ----------

def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _as_dict(x) -> dict:
    """模型的 JSON 形状不可信：说好返回对象数组，它可能给字符串数组。

    complete_json 只保证顶层是对象，嵌套结构由调用方自己防 —— 少一个 isinstance
    就是一个 500，而这个项目的前提是模型再离谱产品也不能崩。
    """
    return x if isinstance(x, dict) else {}


def _fallback_open(topic: str, lang: str = "zh") -> dict:
    """模型不可用时退回角色口头禅 —— 说的还是那个角色的话，只是没有贴合议题。"""
    key = "catch" if lang == "zh" else "catch_en"
    out = {}
    for i, mid in enumerate(roster.IDS):
        out[mid] = {
            "stance": STANCES[_seed(topic, mid) % 3] if i >= 2 else ("pro" if i == 0 else "con"),
            "text": roster.ROSTER[mid][key],
        }
    return {"ministers": out}


# ---------- 开堂 ----------

OPEN_SYS = """你是一场荒诞朝堂喜剧的编剧。十一位动物大臣要就皇帝的议题各自站队。
每位大臣必须严格按自己的偏见发言，绝不能说出别的大臣才会说的话。
每句开场白 25 字以内，要有角色口癖，不要客套。"""


def open_court(topic: str, context: str = "", lang: str = "zh") -> dict:
    sid = store.create_session(topic, context, lang)
    # 奏章背景切句入库，蝴蝶后面就有东西可检索。没有背景就等浣熊往里存。
    library.add_facts(library.split_sentences(context), session_id=sid, source="petition")
    prompt = (f"议题：{topic}\n背景：{context or '（无）'}\n\n大臣名册：\n{roster.roster_block(lang)}\n\n"
              '返回 JSON：{"ministers":{"大臣id":{"stance":"pro|con|undecided","text":"开场白"}, ...}}，'
              "十一位全部要有。至少 3 位 pro、至少 3 位 con。")
    data, _ = llm.complete_json(
        [{"role": "system", "content": f"{OPEN_SYS}\n{LANG_RULE.get(lang, LANG_RULE['zh'])}"},
         {"role": "user", "content": prompt}],
        op="stance", session_id=sid, max_tokens=1200, fallback=_fallback_open(topic, lang))

    mins = _as_dict(data.get("ministers"))
    for mid in roster.IDS:
        m = _as_dict(mins.get(mid))
        stance = m.get("stance") if m.get("stance") in STANCES else "undecided"
        text = (m.get("text") or "……").strip()
        store.add_turn(sid, mid, "opening", stance, text, influence=roster.ROSTER[mid]["weight"])
    return snapshot(sid)


# ---------- 一回合 ----------

ROUND_SYS = """你是荒诞朝堂喜剧的编剧。给定当前立场，写一回合冲突：
两位大臣正面对呛各一句（25 字内），然后一位大臣游说另一位（30 字内）。
被游说者是否倒戈，由我给的 flip 结果决定，你只负责写台词，不要改判。
每个 text 都必须是那位大臣张口说出来的原话：第一人称，不加人名前缀，不写旁白或动作描述。
反例（不许这样写）：「章鱼宰相游说结茧：……」「结茧被说服倒戈了」。"""


def _duel_pair(stances: dict, rnd: int) -> tuple[str, str] | None:
    pro = sorted([m for m, v in stances.items() if v["stance"] == "pro"], key=lambda m: -stances[m]["influence"])
    con = sorted([m for m, v in stances.items() if v["stance"] == "con"], key=lambda m: -stances[m]["influence"])
    if not pro or not con:
        return None
    return pro[rnd % len(pro)], con[rnd % len(con)]


def _lobby_target(stances: dict, rnd: int) -> tuple[str, str] | None:
    """游说：一位有立场的大臣去拉一位未定的。权重越低越容易被拉走（羊最好拉）。"""
    swing = sorted([m for m, v in stances.items() if v["stance"] == "undecided"],
                   key=lambda m: roster.ROSTER[m]["weight"])
    firm = sorted([m for m, v in stances.items() if v["stance"] != "undecided"],
                  key=lambda m: -stances[m]["influence"])
    if not swing or not firm:
        return None
    return firm[rnd % len(firm)], swing[0]


def next_round(session_id: str) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    stances = store.current_stances(session_id)
    rnd = store.count_traces(session_id, "speak")

    duel = _duel_pair(stances, rnd)
    lob = _lobby_target(stances, rnd)

    # 倒戈由代码判定，不交给模型：皇帝倾向 + 双方影响力 + 稳定随机
    flipped, new_stance = False, None
    if lob:
        src, dst = lob
        push = stances[src]["influence"] + s["lean"] * (1 if stances[src]["stance"] == "pro" else -1)
        flipped = (push + (_seed(session_id, dst, str(rnd)) % 100) / 100.0) > 1.0
        new_stance = stances[src]["stance"] if flipped else "undecided"

    undecided = sum(1 for v in stances.values() if v["stance"] == "undecided")
    forced = undecided > MAX_UNDECIDED and not flipped

    # 本轮会开口的人：对呛双方 + 游说双方
    speakers = set(duel or ()) | set(lob or ())

    # 蝴蝶只要上场就先查文库 —— 这是它人设的机制化：先有结论，再去找支持它的材料
    hits = []
    if "moth" in speakers:
        hits = library.search(f"{s['topic']} {s['context']}".strip(),
                              session_id=session_id, minister="moth")

    key = "catch" if s["lang"] == "zh" else "catch_en"
    fb = {"clash": [{"minister": d, "text": roster.ROSTER[d][key]} for d in (duel or [])],
          "lobby": ({"text": roster.ROSTER[lob[0]][key]} if lob else None)}
    lines = fb
    if duel or lob:
        recent = "\n".join(f"{t['minister']}：{t['text']}" for t in s["turns"][-6:])
        prompt = (f"议题：{s['topic']}\n背景：{s['context'] or '（无）'}\n"
                  f"当前立场：{json.dumps({m: v['stance'] for m, v in stances.items()}, ensure_ascii=False)}\n"
                  f"皇帝倾向 lean={s['lean']}（正=偏赞成）\n\n"
                  f"刚才朝堂上说过的话（要接得上，不要重复）：\n{recent}\n\n"
                  f"大臣名册：\n{roster.roster_block(s['lang'])}\n\n"
                  + (f"对呛双方：{duel[0]} vs {duel[1]}\n" if duel else "对呛：无\n")
                  + (f"游说：{lob[0]} 去拉 {lob[1]}，flip={flipped}（true 表示 {lob[1]} 倒戈到 "
                     f"{new_stance}，false 表示顶住了）\n" if lob else "游说：无\n")
                  + (("蝴蝶（moth）从文库里查到这些材料，它只会挑对自己立场有利的引用，"
                      "不利的直接无视：\n"
                      + "\n".join(f"- {h['text']}" for h in hits) + "\n\n") if hits else "")
                  + '返回 JSON：{"clash":[{"minister":"id","text":"…"},{"minister":"id","text":"…"}],'
                    '"lobby":{"text":"…","reply":"…"}}')
        lines, _ = llm.complete_json(
            [{"role": "system", "content": f"{ROUND_SYS}\n{LANG_RULE.get(s['lang'], LANG_RULE['zh'])}"},
             {"role": "user", "content": prompt}],
            op="speak", session_id=session_id, max_tokens=500, fallback=fb)

    said_by: dict[str, str] = {}
    clash = lines.get("clash")
    texts = [_as_dict(x).get("text") for x in (clash if isinstance(clash, list) else [])]

    # 台词按顺序发给「我」选定的这两位，不看模型填的 minister —— 模型经常自己换人上场，
    # 那样代码算出来的对呛（以及为蝴蝶预取的文库材料）就全落空了。规则归代码，台词归模型。
    for i, mid in enumerate(duel or ()):
        said = (texts[i] if i < len(texts) and isinstance(texts[i], str) and texts[i].strip()
                else roster.ROSTER[mid][key]).strip()
        store.add_turn(session_id, mid, "rebuttal", stances[mid]["stance"],
                       said, influence=stances[mid]["influence"])
        said_by[mid] = said

    if lob:
        src, dst = lob
        lo = _as_dict(lines.get("lobby"))
        said = (lo.get("text") or roster.ROSTER[src][key]).strip()
        said_by[src] = said_by.get(src, "") + " " + said
        store.add_turn(session_id, src, "lobby", stances[src]["stance"], said,
                       influence=stances[src]["influence"], target=dst)
        if flipped or forced:
            final = new_stance if flipped else ("pro" if s["lean"] >= 0 else "con")
            store.add_turn(session_id, dst, "lobby", final,
                           (lo.get("reply") or roster.ROSTER[dst][key]).strip(),
                           influence=stances[dst]["influence"] * (1.1 if flipped else 0.9), target=src)

    # 检索到几条 vs 蝴蝶真正引用了几条，差值就是「确认偏误」的可量化形式
    if hits and said_by.get("moth"):
        library.mark_cited(session_id, hits, said_by["moth"])
    # 浣熊是档案官：它翻出来的旧账就是文库的新素材，下一轮蝴蝶就能检索到
    if said_by.get("raccoon"):
        library.add_facts([said_by["raccoon"].strip()], session_id=session_id, source="raccoon")

    return snapshot(session_id)


# ---------- 皇帝干预 ----------

DECREE_LEAN = {"silence": 0.0, "swap": 0.0, "banana": 0.0}


def decree(session_id: str, kind: str, lean_delta: float = 0.0, text: str = "") -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    store.set_lean(session_id, s["lean"] + lean_delta)
    store.add_turn(session_id, "emperor", "decree", "undecided",
                   text.strip() or {"silence": "💥 肃静！", "swap": "🖌 朱笔一挥。",
                                    "banana": "🍌 天降香蕉。"}.get(kind, kind), influence=0.0)
    return snapshot(session_id)


# ---------- 裁决 ----------

VERDICT_SYS = "你是荒诞朝堂喜剧的编剧。用两句话写一段圣旨判词，古腔今用，不超过 50 字。"

VERDICT_ZH = {"approve": "准奏", "reject": "驳回", "shelve": "搁置", "adjourn": "退朝"}


def verdict(session_id: str, choice: str) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    tally = _tally(store.current_stances(session_id))
    fb = {"edict": f"朕意已决：{VERDICT_ZH.get(choice, choice)}。众卿退下。"}
    data, _ = llm.complete_json(
        [{"role": "system", "content": f"{VERDICT_SYS}\n{LANG_RULE.get(s['lang'], LANG_RULE['zh'])}"},
         {"role": "user", "content": f"议题：{s['topic']}\n朕的裁决：{VERDICT_ZH.get(choice, choice)}\n"
                                     f"朝堂票型：赞成 {tally['pro']}、反对 {tally['con']}、未定 {tally['undecided']}\n"
                                     '返回 JSON：{"edict":"判词"}'}],
        op="verdict", session_id=session_id, max_tokens=200, fallback=fb)
    edict = data.get("edict")
    store.add_turn(session_id, "emperor", "verdict", "undecided",
                   (edict if isinstance(edict, str) and edict.strip() else fb["edict"]).strip())
    store.end_session(session_id, choice)
    return snapshot(session_id)


# ---------- 快照：前端和监控台都读这个形状 ----------

def _tally(stances: dict) -> dict:
    t = {k: 0 for k in STANCES}
    for v in stances.values():
        if v["minister"] != "emperor":
            t[v["stance"]] += 1
    return t


def snapshot(session_id: str) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    stances = {m: v for m, v in store.current_stances(session_id).items() if m != "emperor"}
    rounds = store.count_traces(session_id, "speak")
    return {
        "id": s["id"], "topic": s["topic"], "context": s["context"], "lang": s["lang"],
        "status": s["status"], "verdict": s["verdict"], "lean": s["lean"],
        "round": rounds, "rounds_left": max(0, ROUNDS_PER_SESSION - rounds),
        "tally": _tally(stances),
        "ministers": [{"id": m, **roster.ROSTER[m], "stance": v["stance"],
                       "influence": v["influence"]} for m, v in stances.items()],
        "turns": s["turns"],
    }
