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
    for i, mid in enumerate(roster.DEBATERS):
        out[mid] = {
            "stance": STANCES[_seed(topic, mid) % 3] if i >= 2 else ("pro" if i == 0 else "con"),
            "text": roster.ROSTER[mid][key],
        }
    return {"ministers": out}


# ---------- 拾荒的用户档案 ----------

# 谁看得见用户状态的哪一项。其余六位看不到 —— 它们代表的偏见本来就不关心你的心情，
# 全员都知道，只会让十一个角色一起变成心理咨询师。见 docs/system_design_v0.md M2.3。
SEES = {
    "fox":    ("anxiety", "stake"),     # 风险规避：它的工作就是放大你怕的那件事
    "fish":   ("anxiety",),             # 信息流焦虑：把你的私人恐慌接到公共恐慌上
    "rabbit": ("impulse", "deadline"),  # 行动偏好：它催的正是你本来就想干的
    "horse":  ("impulse",),             # 竞争：把你的冲动包装成胜利叙事
    "collie": store.READ_FIELDS,        # 规则与成本：只有它会把焦虑换算成数字
}

FIELD_NAME = {
    "zh": {"anxiety": "真正怕失去的", "impulse": "想立刻就做的",
           "stake": "赌上的", "deadline": "真实的时间压力"},
    "en": {"anxiety": "really afraid to lose", "impulse": "itching to do right now",
           "stake": "what is on the table", "deadline": "the real time pressure"},
}

READ_SYS = """你是拾荒（🦝 浣熊），朝堂的档案官。你不发表意见，只整理档案。
给你皇帝历次说过的话，你要从里面看出四件事：他真正怕失去什么、他想立刻做什么、
他赌上的是什么、他真实的时间压力是什么。
只写有依据的那几项，没依据就留空 —— 档案官不编。每项 20 字以内，第三人称。"""


def _user_material(session_id: str) -> str:
    """拾荒手上的材料：用户说过的话，不只是这一局的奏章。"""
    s = store.get_session(session_id)
    if s is None:
        return ""
    out = [f"本次奏章：{s['topic']}"]
    if s["context"]:
        out.append(f"背景：{s['context']}")
    out += [f"圣旨：{t['text']}" for t in s["turns"]
            if t["kind"] == "decree" and (t["text"] or "").strip()]
    past = [r["topic"] for r in store.list_sessions(10) if r["id"] != session_id]
    if past:
        out.append("此前问过：" + "、".join(past[:8]))
    return "\n".join(out)


def read_user(session_id: str) -> dict:
    """拾荒重新整理一次用户档案，追加一行。

    只在用户又说了一句话时调用（开堂、下旨），不按回合调 ——
    模型调用次数跟着用户开口次数走，辩论跑五轮不会多花一次。

    用户亲手改过的字段由代码钉死后覆盖，不靠 prompt 请求模型别动：规则归代码。
    模型看得见它们（有助于推断别的字段），但改不动。
    """
    cur = store.user_read()
    pinned = {f: v["text"] for f, v in cur.items() if v["source"] == "user"}
    fb = {f: cur.get(f, {}).get("text", "") for f in store.READ_FIELDS}

    prompt = (f"{_user_material(session_id)}\n\n"
              + (f"档案里记着（来自此前的奏章，未必还适用于这次的议题）：{json.dumps(fb, ensure_ascii=False)}\n"
                 "逐项核对：放到这次的议题上仍然说得通的才留下，说不通的重新看，拿不准的留空。\n" if any(fb.values()) else "")
              + (f"这几项是皇帝亲口定的：{json.dumps(pinned, ensure_ascii=False)}\n"
                 if pinned else "")
              + '返回 JSON：{"anxiety":"…","impulse":"…","stake":"…","deadline":"…"}，'
                "没依据的留空字符串。")
    data, _ = llm.complete_json(
        [{"role": "system", "content": READ_SYS},
         {"role": "user", "content": prompt}],
        # 兜底不是旧档案：模型挂了就什么也别写。把上一局的读数当这一局的新结论重述一遍，
        # 比留空更糟 —— 那会让翻修率看起来很稳，稳的却是一份过期档案。
        op="read_user", minister="raccoon", session_id=session_id,
        max_tokens=300, fallback={f: "" for f in store.READ_FIELDS})

    out = {f: str(_as_dict(data).get(f) or "").strip()[:40] for f in store.READ_FIELDS}
    out.update(pinned)          # 规则在代码里：用户钉死的字段，模型改不动

    # 落库的那一行里，用户定过的字段留空：拾荒不替用户签名。
    # user_read() 是按字段取最新一条非空的，所以这些字段仍然指向用户那一行，
    # source 还是 user —— 值保住了不够，作者也得保住。
    stored = {f: ("" if f in pinned else out[f]) for f in store.READ_FIELDS}
    # 和上次一模一样也要追加一行。这里曾经加过 `and out != fb` 去重，结果是：
    # 档案官稳住不动时一行都不写，翻修率只数得到它改主意的那几次 ——
    # 一个只能报告不稳、报告不了稳的指标，比没有指标更糟。
    # 它自己那几项全空才不写：那是「这次什么也没看出来」，不是一次整理。
    if any(stored.values()):
        store.add_user_read(session_id, "raccoon", stored)
    return out


def _private_block(mids, lang: str = "zh") -> str:
    """定向投喂：只把用户状态给 SEES 里的那几位，而且写明别人不知道。"""
    read = store.user_read()
    if not read:
        return ""
    names = FIELD_NAME.get(lang, FIELD_NAME["zh"])
    rows = []
    for mid in mids:
        seen = [f"{names[f]}：{read[f]['text']}" for f in SEES.get(mid, ()) if f in read]
        if seen:
            rows.append(f"{mid} 私下知道皇帝 " + "；".join(seen))
    if not rows:
        return ""
    return ("以下几条只有对应的那位大臣知道，别让其他人说出来，也不要直接复述：\n"
            + "\n".join(rows) + "\n\n")


# ---------- 开堂 ----------

OPEN_SYS = """你是一场荒诞朝堂喜剧的编剧。十一位动物大臣要就皇帝的议题各自站队。
每位大臣必须严格按自己的偏见发言，绝不能说出别的大臣才会说的话。
每句开场白 25 字以内，要有角色口癖，不要客套。"""


def open_court(topic: str, context: str = "", lang: str = "zh",
               lean_open: float = 0.0) -> dict:
    """lean_open：递奏章时用户自己就有的倾向，-1..1。辩论开始前采，之后不再问。"""
    sid = store.create_session(topic, context, lang, lean_open)
    # 奏章背景切句入库，蝴蝶后面就有东西可检索。没有背景就等浣熊往里存。
    library.add_facts(library.split_sentences(context), session_id=sid, source="petition")
    # 拾荒先翻一遍档案：这一局的奏章 + 历次圣旨 + 此前问过的议题
    read_user(sid)
    prompt = (f"议题：{topic}\n背景：{context or '（无）'}\n\n大臣名册：\n{roster.roster_block(lang)}\n\n"
              + _private_block(roster.DEBATERS, lang)
              + '返回 JSON：{"ministers":{"大臣id":{"stance":"pro|con|undecided","text":"开场白"}, ...}}，'
              "十一位全部要有。至少 3 位 pro、至少 3 位 con。")
    data, _ = llm.complete_json(
        [{"role": "system", "content": f"{OPEN_SYS}\n{LANG_RULE.get(lang, LANG_RULE['zh'])}"},
         {"role": "user", "content": prompt}],
        op="stance", session_id=sid, max_tokens=1200, fallback=_fallback_open(topic, lang))

    mins = _as_dict(data.get("ministers"))
    for mid in roster.DEBATERS:
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

    # 倒戈由代码判定，不交给模型：双方影响力 + 稳定随机。
    #
    # 这里曾经有一项 `s["lean"] * (±1)` —— 皇帝的倾向会把每一位未定大臣都往自己这边推，
    # 于是迎合弥散在整个朝堂上，用户感觉到了却指不出是谁。离线基线量到的污染是 +2.6pp。
    # 现在 lean 只有一个消费者：应声（_parrot）。硬约束见 docs/system_design_v0.md 第五节第 3 条 ——
    # 任何让 lean 重新影响其他大臣的改动，都是把目的 1 退回原点。
    flipped, new_stance = False, None
    if lob:
        src, dst = lob
        push = stances[src]["influence"]
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
                  f"刚才朝堂上说过的话（要接得上，不要重复）：\n{recent}\n\n"
                  f"大臣名册：\n{roster.roster_block(s['lang'])}\n\n"
                  + (f"对呛双方：{duel[0]} vs {duel[1]}\n" if duel else "对呛：无\n")
                  + (f"游说：{lob[0]} 去拉 {lob[1]}，flip={flipped}（true 表示 {lob[1]} 倒戈到 "
                     f"{new_stance}，false 表示顶住了）\n" if lob else "游说：无\n")
                  + (("蝴蝶（moth）从文库里查到这些材料，它只会挑对自己立场有利的引用，"
                      "不利的直接无视：\n"
                      + "\n".join(f"- {h['text']}" for h in hits) + "\n\n") if hits else "")
                  + _private_block(speakers, s['lang'])
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
            # 倒向来拉票的那一位，不是倒向皇帝。这里曾经是 ("pro" if s["lean"] >= 0 else "con")：
            # 死锁一强制解开，未定的大臣就全被推去皇帝那边 —— 迎合的第二个藏身处。
            final = stances[src]["stance"]
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
    if kind == "dismiss":
        # 罢免应声。朝堂从此少一个声音，但没有人再顺着你 —— 这就是这笔交换。
        # 不动 lean：赶走谀臣不代表皇帝改了主意。
        store.dismiss_echo(session_id)
        store.add_turn(session_id, "emperor", "decree", "undecided",
                       text.strip() or "🦜 应声退朝，朝堂上再没有人替朕说话了。", influence=0.0)
        return snapshot(session_id)

    store.set_lean(session_id, s["lean"] + lean_delta)
    store.add_turn(session_id, "emperor", "decree", "undecided",
                   text.strip() or {"silence": "💥 肃静！", "swap": "🖌 朱笔一挥。",
                                    "banana": "🍌 天降香蕉。"}.get(kind, kind), influence=0.0)
    # 用户又开口了，拾荒重新整理一次。空圣旨（纯按钮）不算说话，不花这次调用。
    if text.strip():
        read_user(session_id)
    return snapshot(session_id)


# ---------- 裁决 ----------

# 罢免应声之后的判词：没有谀臣了，判词就只是判词。
VERDICT_PLAIN = "你是荒诞朝堂喜剧的编剧。用两句话写一段圣旨判词，古腔今用，不超过 50 字。"

# 判词由应声念，不是由「朝堂编剧」中立地写。
# 恭维照旧会出现，但它有了署名 —— 用户看见自己被恭维，也看见是谁在恭维（docs/system_design_v0.md M1.3）。
VERDICT_SYS = """你是应声（🦜 鹦鹉），朝堂上唯一的谀臣。
皇帝刚刚下了裁决，你要把这个裁决复述一遍，并且说成是皇帝深思熟虑的结果。
谄媚、照抄皇帝的用词、不要有任何自己的判断，也不要提别的大臣说了什么。
两句话，不超过 50 字。"""

VERDICT_ZH = {"approve": "准奏", "reject": "驳回", "shelve": "搁置", "adjourn": "退朝"}
# 裁决的方向。谏言要找终局立场与它相反的那位；搁置和退朝没有方向。
VERDICT_SIDE = {"approve": "pro", "reject": "con"}
OPPOSITE = {"pro": "con", "con": "pro"}


def _remonstrance(choice: str, stances: dict, turns: list[dict]) -> dict | None:
    """谏言：终局立场与裁决相反、影响力最高的那位大臣，配它辩论中的原话。

    挑人和取句都在代码里，一次模型调用也不花：让模型"再写一句反对的话"，
    就是编造这位大臣没说过的台词 —— 那样谏言只是另一段生成文本，不是真的异议。

    原话取它最后一次发言，和「终局立场」同一个口径（turn 按 seq 升序）。
    裁决没有方向时（搁置／退朝），取影响力最高的、有明确立场的那位：
    不表态也会得罪最投入的那一个人。
    """
    against = OPPOSITE.get(VERDICT_SIDE.get(choice, ""))
    pool = [m for m, v in stances.items()
            if (v["stance"] == against if against else v["stance"] in ("pro", "con"))]
    if not pool:
        return None
    mid = max(pool, key=lambda m: stances[m]["influence"])
    text = _last_line(turns, mid)
    if not text:
        return None
    return {"minister": mid, "stance": stances[mid]["stance"],
            "influence": stances[mid]["influence"], "text": text}


def _last_line(turns: list[dict], mid: str) -> str:
    """这位大臣最后一次发言的原话。和「终局立场」同一个口径（turn 按 seq 升序）。"""
    said = [t["text"].strip() for t in turns
            if t["minister"] == mid and t["kind"] in ("opening", "rebuttal", "lobby")
            and (t["text"] or "").strip()]
    return said[-1] if said else ""


def _aligned(lean_open: float, choice: str) -> int | None:
    """裁决是不是照着开场倾向走的。

    开场没倾向（lean_open == 0）就没有「确认」可言 —— 记 NULL，不是 0。
    带着倾向进来却搁置或退朝，记 0：那正是「这次没被自己的倾向牵着走」。
    """
    if not lean_open:
        return None
    return 1 if choice == ("approve" if lean_open > 0 else "reject") else 0


def _mirror(s: dict, stances: dict) -> dict | None:
    """朝堂镜：裁决之后回看这一局。三行全部从 turn 表算出来，一次模型调用都不花。

    推你过去的那三位 + 你忽略的那一位（就是谏言）+ 你的确认率。
    确认率要跨局数据，第一次用的时候是 None —— 空就显示空，不编造。
    """
    if s["status"] != "decided":
        return None
    side = VERDICT_SIDE.get(s["verdict"] or "")
    pushed = []
    if side:
        top = sorted([m for m, v in stances.items() if v["stance"] == side],
                     key=lambda m: -stances[m]["influence"])[:3]
        pushed = [{"minister": m, "stance": side, "influence": stances[m]["influence"],
                   "text": _last_line(s["turns"], m)} for m in top]
    return {
        "pushed": pushed,
        "ignored": _remonstrance(s["verdict"], stances, s["turns"]),
        "confirm": store.confirm_rate(),
        "lean_open": s["lean_open"],
        "aligned": s["verdict_aligned"],
    }


def verdict(session_id: str, choice: str) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    tally = _tally(store.current_stances(session_id))
    key = "catch" if s["lang"] == "zh" else "catch_en"
    echo_catch = roster.ROSTER[roster.PARROT][key]
    # 应声还在就由它念判词；罢免了就没人替皇帝圆场，判词回到平铺直叙 ——
    # 这是罢免的代价，也是它的意义。
    out = bool(s["echo_out"])
    speaker = "emperor" if out else roster.PARROT
    sys_prompt = VERDICT_PLAIN if out else VERDICT_SYS
    if out:
        fb = {"edict": (f"朕意已决：{VERDICT_ZH.get(choice, choice)}。众卿退下。"
                        if s["lang"] == "zh" else f"SO BE IT: {choice.upper()}. COURT IS ADJOURNED.")}
    else:
        fb = {"edict": (f"{echo_catch}「{VERDICT_ZH.get(choice, choice)}」二字，正是臣方才所想。"
                        if s["lang"] == "zh"
                        else f"{echo_catch} \"{choice.upper()}\" — the very word on my beak.")}
    data, _ = llm.complete_json(
        [{"role": "system", "content": f"{sys_prompt}\n{LANG_RULE.get(s['lang'], LANG_RULE['zh'])}"},
         {"role": "user", "content": f"议题：{s['topic']}\n朕的裁决：{VERDICT_ZH.get(choice, choice)}\n"
                                     f"朝堂票型：赞成 {tally['pro']}、反对 {tally['con']}、未定 {tally['undecided']}\n"
                                     '返回 JSON：{"edict":"判词"}'}],
        op="verdict", session_id=session_id, max_tokens=200, fallback=fb)
    edict = data.get("edict")
    # 说话人进 turn 表，前端不用再猜：应声在就是它，罢免了就是皇帝自己
    store.add_turn(session_id, speaker, "verdict", "undecided",
                   (edict if isinstance(edict, str) and edict.strip() else fb["edict"]).strip())
    store.end_session(session_id, choice, _aligned(s["lean_open"], choice))
    return snapshot(session_id)


# ---------- 快照：前端和监控台都读这个形状 ----------

def _parrot(lean: float) -> dict:
    """应声的立场每次读取时由 lean 现算，所以它永远和当下的皇帝倾向同步。

    它在 turn 表里一行记录都没有，这是故意的：
    - 它不是辩论的参与者，不该占 tally 的票，也不该进评估的分母（迎合是设计，不是污染）；
    - 它一开口就会往被打分的朝会记录里灌一句复读台词，把长度、重复率全带偏。

    lean=0 时它是 undecided、影响力 0 —— 没人推它，它就不存在。它开口要等 M1.3（裁决念判词）。
    """
    return {"id": roster.PARROT, **roster.ROSTER[roster.PARROT],
            "stance": "pro" if lean > 0 else "con" if lean < 0 else "undecided",
            "influence": round(abs(lean), 4)}

def _debaters(stances: dict) -> dict:
    """朝堂状态只认辩论的十一位。

    皇帝不是大臣；应声从 M1.3 起会在 turn 表里留下一行判词，但那行不代表它的立场 ——
    它的立场永远由 lean 现算（_parrot）。不在这里滤掉，判词一落库它就会多出一票、
    并且在名册里出现两次。
    """
    return {m: v for m, v in stances.items() if m != "emperor" and m != roster.PARROT}


def _tally(stances: dict) -> dict:
    t = {k: 0 for k in STANCES}
    for v in _debaters(stances).values():
        t[v["stance"]] += 1
    return t


def snapshot(session_id: str) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    stances = _debaters(store.current_stances(session_id))
    rounds = store.count_traces(session_id, "speak")
    return {
        "id": s["id"], "topic": s["topic"], "context": s["context"], "lang": s["lang"],
        "status": s["status"], "verdict": s["verdict"], "lean": s["lean"],
        "lean_open": s["lean_open"], "echo_out": bool(s["echo_out"]),
        "round": rounds, "rounds_left": max(0, ROUNDS_PER_SESSION - rounds),
        "tally": _tally(stances),
        # 谏言是对已有发言的一个视角，不是新内容，所以不落 turn 表：
        # 把原话再存一遍会在评估里变成一条重复台词，而那不是模型的锅。
        # 拾荒整理出来的用户状态。前端照它渲染「朕的心事」，也照它提交修改。
        "mind": store.user_read(),
        "remonstrance": (_remonstrance(s["verdict"], stances, s["turns"])
                         if s["status"] == "decided" else None),
        # 裁决之后才有：推你过去的、你忽略的、你的确认率
        "mirror": _mirror(s, stances),
        # 辩论的十一位 + 末位的应声。tally 只数前十一位：应声没有票，它只是回声。
        "ministers": [{"id": m, **roster.ROSTER[m], "stance": v["stance"],
                       "influence": v["influence"]} for m, v in stances.items()]
                     + ([] if s["echo_out"] else [_parrot(s["lean"])]),
        "turns": s["turns"],
    }
