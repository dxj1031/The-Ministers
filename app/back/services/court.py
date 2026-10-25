"""朝堂辩论引擎。

规则由代码定死（谁能对呛、谁会倒戈、死锁上限），模型只负责把具体议题填进这些槽位。
这样换模型、模型挂掉、模型胡说都不会让玩法崩掉 —— 见 README「角色先于模型」。

每回合恰好一次模型调用，落一行 llm_trace。
"""
import hashlib
import json
import re

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


def _text(value, fallback="", limit=160) -> str:
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else fallback


def _sources(s: dict) -> dict:
    """只引用确实存在的输入；模型写的出处和数字不作为已核实事实。"""
    out = {"topic": {"text": s["topic"], "kind": "topic"}}
    for i, text in enumerate(p.strip() for p in re.split(r"[。！？；\n]", s["context"]) if p.strip()):
        out[f"context-{i + 1}"] = {"text": text, "kind": "context"}
    for t in s["turns"]:
        if t["minister"] == "emperor" and t["kind"] == "decree" and t["text"]:
            out[f"emperor-{t['seq']}"] = {"text": t["text"], "kind": "emperor"}
    for f in s.get("factors", []):
        if f["active"]:
            out[f"factor-{f['id']}"] = {"text": f["text"], "kind": f["kind"]}
    return out


def _factor_force(s: dict, src: str) -> tuple[float, list[str]]:
    interests = {"risk": ("fox", "fish", "snake"), "opportunity": ("rabbit", "horse", "banana"),
                 "constraint": ("collie", "octopus"), "fact": ("raccoon", "moth", "sheep")}
    ids = [f["id"] for f in s.get("factors", []) if f["active"] and src in interests.get(f["kind"], ())]
    return min(0.3, len(ids) * 0.1), ids


def _argument(data: dict, sources: dict) -> dict:
    reason = _text(data.get("reason"))
    source_id = _text(data.get("source"), limit=50)
    source = sources.get(source_id)
    claimed = re.search(r"新闻|研究显示|数据证明|统计表明|据报道|上次|去年|上周|曾承诺", reason + _text(data.get("text")))
    unsupported = bool(claimed and not any(claimed.group() in row["text"] for row in sources.values()))
    return {"reason": reason, "source": source_id if source else "",
            "evidence": source["text"] if source else "",
            "basis": "unverified" if unsupported else (source["kind"] if source else ("assumption" if reason else "missing"))}


def _alliances(turns: list[dict]) -> list[list[str]]:
    pairs = set()
    for t in turns:
        d = t.get("detail") or {}
        if d.get("from_stance") and d["from_stance"] != t["stance"]:
            pairs = {p for p in pairs if t["minister"] not in p}
        if d.get("outcome") == "allied" and t.get("target"):
            pairs.add(tuple(sorted((t["minister"], t["target"]))))
    return [list(p) for p in sorted(pairs)]


def _politics(s: dict, stances: dict, rnd: int) -> tuple[str, tuple[str, str] | None]:
    allies = _alliances(s["turns"])
    firm = [m for m in stances if stances[m]["stance"] != "undecided"]
    # 同阵营先结盟，出现对立时施压；背盟必须先有真实同盟，不能凭空表演。
    if rnd % 4 == 1:
        options = [(a, b) for i, a in enumerate(firm) for b in firm[i + 1:]
                   if stances[a]["stance"] == stances[b]["stance"]
                   and sorted((a, b)) not in allies]
        if options:
            return "ally", options[rnd % len(options)]
    if rnd % 4 in (2, 3):
        members = {m for p in allies for m in p}
        options = [(a, b) for a in firm for b in firm
                   if stances[a]["stance"] != stances[b]["stance"]
                   and (rnd % 4 != 3 or b in members)]
        if options:
            pair = max(options, key=lambda p: stances[p[0]]["influence"] - stances[p[1]]["influence"])
            return ("defect" if rnd % 4 == 3 else "threaten"), pair
    pair = _lobby_target(stances, rnd)
    if not pair and len(firm) > 1:
        options = [(a, b) for a in firm for b in firm if stances[a]["stance"] != stances[b]["stance"]]
        if options:
            pair = options[rnd % len(options)]
    return "lobby", pair


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
每位都要写 text（25 字内的主张）、reason（40–70 字，解释因果、代价或反例）、source（输入材料的编号）。
不能只有结论或口号。引用已有材料支持推理；材料不足就指出缺什么，source 留空。
不要编造研究、数字或既成事实，未核实的推测必须在 reason 中明确写“如果”或“可能”。
台词是直接说出来的话，第一人称，不写动作旁白。保留角色个性，但不要为了口癖牺牲论据。"""


def open_court(topic: str, context: str = "", lang: str = "zh",
               lean_open: float = 0.0) -> dict:
    """lean_open：递奏章时用户自己就有的倾向，-1..1。辩论开始前采，之后不再问。"""
    sid = store.create_session(topic, context, lang, lean_open)
    # 奏章背景切句入库，蝴蝶后面就有东西可检索。没有背景就等浣熊往里存。
    library.add_facts(library.split_sentences(context), session_id=sid, source="petition")
    # 拾荒先翻一遍档案：这一局的奏章 + 历次圣旨 + 此前问过的议题
    read_user(sid)
    s = store.get_session(sid)
    sources = _sources(s)
    prompt = (f"议题：{topic}\n背景：{context or '（无）'}\n\n大臣名册：\n{roster.roster_block(lang)}\n\n"
              + _private_block(roster.DEBATERS, lang)
              + f"可引用的输入材料（编号对应原文）：{json.dumps(sources, ensure_ascii=False)}\n"
              + '返回 JSON：{"ministers":{"大臣id":{"stance":"pro|con|undecided","text":"主张","reason":"论证","source":"材料编号或空串"}, ...}}，'
              "十一位全部要有。至少 3 位 pro、至少 3 位 con。")
    data, _ = llm.complete_json(
        [{"role": "system", "content": f"{OPEN_SYS}\n{LANG_RULE.get(lang, LANG_RULE['zh'])}"},
         {"role": "user", "content": prompt}],
        op="stance", session_id=sid, max_tokens=3000, fallback=_fallback_open(topic, lang))

    mins = _as_dict(data.get("ministers"))
    for mid in roster.DEBATERS:
        m = _as_dict(mins.get(mid))
        stance = m.get("stance") if m.get("stance") in STANCES else "undecided"
        text = _text(m.get("text"), "……", 80)
        store.add_turn(sid, mid, "opening", stance, text, influence=roster.ROSTER[mid]["weight"],
                       detail={**_argument(m, sources), "round": 0, "move": "opening"})
    return snapshot(sid)


# ---------- 一回合 ----------

ROUND_SYS = """你是荒诞朝堂喜剧的编剧。给定当前立场，写一回合冲突：
两位大臣对呛后，另外两位加入群辩，分别指出漏洞、补充证据或提出条件，不要轮流重复结论。
然后按指定行动写游说、施压、结盟或拉拢背盟的交涉及对方回应。施压仅限议事中的成本、条件、资源和合作，不是暴力威胁。
每条都写 text（25 字内的主张）、reason（40–70 字的因果、反例或代价）、source（给定材料编号或空串）。
text 和 reason 都用指定 minister 的第一人称，直接对 target 说话；不要称呼自己，不要用“某某大臣认为”的旁白。
严格按给出的 minister 顺序填槽位，lobby.text 属于发起人，lobby.reply 属于被交涉者，不能交换角色。
引用对方的具体论点再回应。皇帝提问要回答疑问，补充事实要核对影响，约束要检验能否满足；不能一律恭维。
没有材料就标明假设或追问缺失信息，禁止编造数字、研究和来源。
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
    if s["status"] == "decided" or store.count_traces(session_id, "speak") >= ROUNDS_PER_SESSION:
        return snapshot(session_id)
    stances = _debaters(store.current_stances(session_id))
    rnd = store.count_traces(session_id, "speak")

    duel = _duel_pair(stances, rnd)
    # 圣旨只作用于下一轮。用最后一次辩论发言划界，避免每轮重复消费同一道旨。
    last_speech = max((t["seq"] for t in s["turns"]
                       if t["kind"] in ("opening", "rebuttal", "lobby")), default=0)
    commands = [t.get("target") for t in s["turns"]
                if t["kind"] == "decree" and t["seq"] > last_speech
                and t.get("target") in ("swap", "banana")]
    if commands and commands[-1] == "swap":
        duel = _duel_pair(stances, rnd + 1)
    elif commands and commands[-1] == "banana" and "banana" in stances:
        opponents = sorted((m for m in stances if m != "banana"),
                           key=lambda m: (stances[m]["stance"] == stances["banana"]["stance"],
                                          -stances[m]["influence"]))
        if opponents:
            duel = ("banana", opponents[0])
    if not duel and len(stances) >= 2:
        # 同阵营也可争论代价和实施条件；模型全写未定时，群辩仍须有真实参与者。
        duel = tuple(sorted(stances, key=lambda m: -stances[m]["influence"])[:2])
    move, lob = _politics(s, stances, rnd)
    rest = [m for m in roster.DEBATERS if m in stances and m not in (duel or ()) and m not in (lob or ())]
    floor = (rest[rnd % len(rest):] + rest[:rnd % len(rest)])[:2] if rest else []
    sources = _sources(s)
    allies = _alliances(s["turns"])
    pressure = 0.0
    shield = 0.0
    roll = 0.0

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
        pressure = min(0.24, sum(0.08 for t in s["turns"] if t.get("target") == dst
                                and t["kind"] in ("lobby", "floor")))
        shield = 0.15 if any(dst in p for p in allies) else 0.0
        factor_force, factor_ids = _factor_force(s, src)
        roll = (_seed(session_id, dst, str(rnd)) % 100) / 100.0
        flipped = move != "ally" and (push + pressure + factor_force - shield + roll) > 1.0
        new_stance = stances[src]["stance"] if flipped else "undecided"

    undecided = sum(1 for v in stances.values() if v["stance"] == "undecided")
    forced = bool(lob and move != "ally" and stances[lob[1]]["stance"] == "undecided"
                  and undecided > MAX_UNDECIDED and not flipped)
    if lob:
        new_stance = stances[lob[0]]["stance"] if flipped or forced else stances[lob[1]]["stance"]

    # 本轮会开口的人：对呛双方 + 游说双方
    speakers = set(duel or ()) | set(lob or ()) | set(floor)

    # 蝴蝶只要上场就先查文库 —— 这是它人设的机制化：先有结论，再去找支持它的材料
    hits = []
    if "moth" in speakers:
        hits = library.search(f"{s['topic']} {s['context']}".strip(),
                              session_id=session_id, minister="moth")

    key = "catch" if s["lang"] == "zh" else "catch_en"
    fb = {"clash": [{"minister": d, "text": roster.ROSTER[d][key]} for d in (duel or [])],
          "floor": [{"text": roster.ROSTER[d][key]} for d in floor],
          "lobby": ({"text": roster.ROSTER[lob[0]][key]} if lob else None)}
    lines = fb
    if speakers:
        shape = {"clash": [{"minister": m, "text": "25字内主张", "reason": "第一人称论证", "source": "材料编号或空串"} for m in (duel or ())],
                 "floor": [{"minister": m, "target": (duel[i % 2] if duel else ""), "text": "回应对方具体论点", "reason": "第一人称论证", "source": "材料编号或空串"} for i, m in enumerate(floor)],
                 "lobby": ({"minister": lob[0], "target": lob[1], "text": "发起者说的话", "reason": "发起者的第一人称理由", "source": "材料编号或空串",
                            "reply_minister": lob[1], "reply": "被交涉者对发起者说的话", "reply_reason": "被交涉者的第一人称理由", "reply_source": "材料编号或空串"} if lob else None)}
        recent = "\n".join(f"#{t['seq']} {t['minister']}→{t.get('target') or '全场'}：{t['text']}；"
                           f"理由：{(t.get('detail') or {}).get('reason', '')}" for t in s["turns"][-12:])
        emperor = [t for t in s["turns"] if t["minister"] == "emperor" and t["kind"] == "decree"][-4:]
        prompt = (f"议题：{s['topic']}\n背景：{s['context'] or '（无）'}\n"
                  f"当前立场：{json.dumps({m: v['stance'] for m, v in stances.items()}, ensure_ascii=False)}\n"
                  f"刚才朝堂上说过的话（要接得上，不要重复）：\n{recent}\n\n"
                  f"皇帝最近的发言（必须回应内容，可质疑但不奉承）：{json.dumps(emperor, ensure_ascii=False)}\n"
                  f"可引用的输入材料：{json.dumps(sources, ensure_ascii=False)}\n"
                  f"局势词条墙：{json.dumps(s.get('factors', []), ensure_ascii=False)}。active=false 的词条已被猫皇切掉，不能继续作为当前约束或论据。\n"
                  f"大臣名册：\n{roster.roster_block(s['lang'])}\n\n"
                  + (f"对呛双方：{duel[0]} vs {duel[1]}\n" if duel else "对呛：无\n")
                  + "同立场时争论实施条件、代价与反例，不要假装投票方向相反。\n"
                  + f"群辩顺序：{json.dumps(floor)}。每位回应对呛中的具体论点；写出 target（回应谁）。\n"
                  + (f"交涉行动={move}：{lob[0]} 对 {lob[1]}，flip={flipped or forced}，"
                     f"结果={'同阵营结盟成功，双方明确承诺' if move == 'ally' else ('改变态度' if flipped or forced else '拒绝改变立场')}，"
                     f"目标最终立场={new_stance}，不要改判。\n" if lob else "游说：无\n")
                  + (("蝴蝶（moth）从文库里查到这些材料，它只会挑对自己立场有利的引用，"
                      "不利的直接无视：\n"
                      + "\n".join(f"- {h['text']}" for h in hits) + "\n\n") if hits else "")
                  + _private_block(speakers, s['lang'])
                  + "按以下固定发言人结构返回 JSON，不要交换角色：" + json.dumps(shape, ensure_ascii=False))
        lines, _ = llm.complete_json(
            [{"role": "system", "content": f"{ROUND_SYS}\n{LANG_RULE.get(s['lang'], LANG_RULE['zh'])}"},
             {"role": "user", "content": prompt}],
            op="speak", session_id=session_id, max_tokens=1800, fallback=fb)

    said_by: dict[str, str] = {}
    clash = lines.get("clash")
    texts = [_as_dict(x).get("text") for x in (clash if isinstance(clash, list) else [])]

    # 台词按顺序发给「我」选定的这两位，不看模型填的 minister —— 模型经常自己换人上场，
    # 那样代码算出来的对呛（以及为蝴蝶预取的文库材料）就全落空了。规则归代码，台词归模型。
    for i, mid in enumerate(duel or ()):
        said = (texts[i] if i < len(texts) and isinstance(texts[i], str) and texts[i].strip()
                else roster.ROSTER[mid][key]).strip()
        store.add_turn(session_id, mid, "rebuttal", stances[mid]["stance"],
                       said, influence=stances[mid]["influence"], target=duel[1 - i],
                       detail={**_argument(_as_dict(clash[i]) if isinstance(clash, list) and i < len(clash) else {}, sources),
                               "round": rnd + 1, "move": "challenge"})
        said_by[mid] = said

    floor_data = lines.get("floor") if isinstance(lines.get("floor"), list) else []
    for i, mid in enumerate(floor):
        item = _as_dict(floor_data[i]) if i < len(floor_data) else {}
        proposed = _text(item.get("target"), limit=50)
        target = proposed if proposed in speakers and proposed != mid else (duel[i % 2] if duel else None)
        said = _text(item.get("text"), roster.ROSTER[mid][key], 80)
        previous = [t for t in store.get_session(session_id)["turns"] if t["minister"] == target]
        store.add_turn(session_id, mid, "floor", stances[mid]["stance"], said,
                       influence=stances[mid]["influence"], target=target,
                       detail={**_argument(item, sources), "round": rnd + 1, "move": "challenge",
                               "reply_to": previous[-1]["seq"] if previous else None})
        said_by[mid] = said

    if lob:
        src, dst = lob
        lo = _as_dict(lines.get("lobby"))
        said = _text(lo.get("text"), roster.ROSTER[src][key], 80)
        said_by[src] = said_by.get(src, "") + " " + said
        store.add_turn(session_id, src, "lobby", stances[src]["stance"], said,
                       influence=stances[src]["influence"], target=dst,
                       detail={**_argument(lo, sources), "round": rnd + 1, "move": move, "outcome": "offer"})
        cause_seq = store.get_session(session_id)["turns"][-1]["seq"]
        reply_arg = _argument({"reason": lo.get("reply_reason"), "source": lo.get("reply_source")}, sources)
        changed = flipped or forced
        final = stances[src]["stance"] if changed else stances[dst]["stance"]
        former = [p for p in allies if dst in p] if changed else []
        outcome = "allied" if move == "ally" else ("defected" if former and changed else ("flipped" if changed else "resisted"))
        detail = {**reply_arg, "round": rnd + 1, "move": move, "outcome": outcome,
                  "from_stance": stances[dst]["stance"], "reply_to": cause_seq, "former_allies": former,
                  "drivers": {"influence": round(stances[src]["influence"], 2),
                              "pressure": round(pressure, 2), "alliance_shield": shield, "forced": forced,
                              "factor_force": factor_force, "factors": factor_ids}}
        detail["drivers"].update({"uncertainty": roll, "score": round(push + pressure + factor_force - shield + roll, 2), "threshold": 1.0})
        if changed:
            # 倒向来拉票的那一位，不是倒向皇帝。这里曾经是 ("pro" if s["lean"] >= 0 else "con")：
            # 死锁一强制解开，未定的大臣就全被推去皇帝那边 —— 迎合的第二个藏身处。
            final = stances[src]["stance"]
            store.add_turn(session_id, dst, "lobby", final,
                           _text(lo.get("reply"), roster.ROSTER[dst][key], 80),
                           influence=stances[dst]["influence"] * (1.1 if flipped else 0.9), target=src, detail=detail)
        else:
            store.add_turn(session_id, dst, "lobby", stances[dst]["stance"],
                           _text(lo.get("reply"), ("臣愿结盟，共同守住条件。" if s["lang"] == "zh" else "I agree to this alliance.")
                                 if move == "ally" else ("臣仍有疑虑，暂不附议。" if s["lang"] == "zh" else "I still have doubts."), 80),
                           influence=stances[dst]["influence"], target=src, detail=detail)

    # 检索到几条 vs 蝴蝶真正引用了几条，差值就是「确认偏误」的可量化形式
    if hits and said_by.get("moth"):
        library.mark_cited(session_id, hits, said_by["moth"])
    # 浣熊是档案官：它翻出来的旧账就是文库的新素材，下一轮蝴蝶就能检索到
    if said_by.get("raccoon"):
        library.add_facts([said_by["raccoon"].strip()], session_id=session_id, source="raccoon")

    return snapshot(session_id)


# ---------- 皇帝干预 ----------

DECREE_LEAN = {"silence": 0.0, "swap": 0.0, "banana": 0.0}


def decree(session_id: str, kind: str, lean_delta: float = 0.0, text: str = "", target: str | None = None) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    if s["status"] == "decided":
        raise ValueError("朝会已裁决，请另开一场。")
    if target and target not in roster.DEBATERS:
        raise ValueError("请指定场上的大臣，或向全场发言。")
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
                                    "banana": "🍌 天降香蕉。"}.get(kind, kind), influence=0.0, target=target or kind,
                   detail={"move": kind, "round": store.count_traces(session_id, "speak")})
    # 用户又开口了，拾荒重新整理一次。空圣旨（纯按钮）不算说话，不花这次调用。
    if text.strip() and kind not in ("question", "fact", "constraint"):
        read_user(session_id)
    return snapshot(session_id)


def factor(session_id: str, text: str = "", kind: str = "risk", factor_id: str = "",
           active: bool = True) -> dict:
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    if s["status"] == "decided":
        raise ValueError("朝会已裁决，词条墙已封存。")
    factors = s.get("factors", [])
    if factor_id:
        item = next((f for f in factors if f["id"] == factor_id), None)
        if item is None:
            raise ValueError("找不到这个词条。")
        if item["active"] == active:
            return snapshot(session_id)
        item["active"] = active
        outcome = "restored" if active else "cut"
    else:
        if kind not in ("risk", "opportunity", "constraint", "fact") or not text.strip():
            raise ValueError("请填写词条，并选择风险、机会、约束或事实。")
        if len(factors) >= 16:
            raise ValueError("本场最多 16 个词条，可以切掉暂不考虑的词条。")
        item = {"id": hashlib.sha256(f"{session_id}|{len(factors)}|{text}".encode()).hexdigest()[:10],
                "text": text.strip()[:160], "kind": kind, "active": True}
        factors.append(item)
        outcome = "added"
    store.set_factors(session_id, factors)
    verb = {"added": "加入", "cut": "切掉", "restored": "恢复"}[outcome]
    store.add_turn(session_id, "emperor", "factor", "undecided", f"{verb}词条：{item['text']}",
                   detail={"move": "factor", "outcome": outcome, "factor": dict(item),
                           "round": store.count_traces(session_id, "speak")})
    return snapshot(session_id)


def respond(session_id: str) -> dict:
    """插话之后立刻得到两种视角的回应；不消耗五轮群辩，也不强迫大臣迎合。"""
    s = store.get_session(session_id)
    if s is None:
        raise KeyError(session_id)
    if s["status"] == "decided":
        raise ValueError("朝会已裁决。")
    messages = [t for t in s["turns"] if t["minister"] == "emperor" and t["kind"] in ("decree", "factor")]
    if not messages:
        raise ValueError("请先发言或调整词条。")
    message = messages[-1]
    if any(t["kind"] == "reply" and (t.get("detail") or {}).get("reply_to") == message["seq"] for t in s["turns"]):
        return snapshot(session_id)
    stances = _debaters(store.current_stances(session_id))
    ranked = sorted(stances, key=lambda m: -stances[m]["influence"])
    first = message["target"] if message.get("target") in stances else ranked[0]
    other = [m for m in ranked if m != first and stances[m]["stance"] != stances[first]["stance"]]
    speakers = [first] + (other or [m for m in ranked if m != first])[:1]
    sources = _sources(s)
    prompt = (f"议题：{s['topic']}\n皇帝的发言：{message['text']}\n"
              f"发言形式：{(message.get('detail') or {}).get('move', 'question')}\n"
              f"回应顺序：{speakers}，立场不变：{json.dumps({m: stances[m]['stance'] for m in speakers})}\n"
              f"刚才的论点：{json.dumps(s['turns'][-10:], ensure_ascii=False)}\n"
              f"词条墙（切掉的不得继续引用）：{json.dumps(s.get('factors', []), ensure_ascii=False)}\n"
              f"输入材料：{json.dumps(sources, ensure_ascii=False)}\n名册：{roster.roster_block(s['lang'])}\n"
              "按固定发言人返回 JSON：" + json.dumps({"replies": [{"minister": m, "text": "直接回答皇帝，25字内",
                "reason": "该大臣的第一人称论证，40–70字", "source": "材料编号或空串"} for m in speakers]}, ensure_ascii=False))
    data, _ = llm.complete_json(
        [{"role": "system", "content": ROUND_SYS + "\n只回答皇帝刚才的内容，不再生成对呛或游说。\n" + LANG_RULE.get(s["lang"], LANG_RULE["zh"])},
         {"role": "user", "content": prompt}], op="reply", session_id=session_id, max_tokens=700,
        fallback={"replies": [{"text": "模型暂不可用，臣不能假装已经论证。" if s["lang"] == "zh" else "The model is unavailable; I cannot justify a reply."} for _ in speakers]})
    replies = data.get("replies") if isinstance(data.get("replies"), list) else []
    for i, mid in enumerate(speakers):
        item = _as_dict(replies[i]) if i < len(replies) else {}
        store.add_turn(session_id, mid, "reply", stances[mid]["stance"], _text(item.get("text"), "……", 80),
                       influence=stances[mid]["influence"], target="emperor",
                       detail={**_argument(item, sources), "move": "answer", "round": store.count_traces(session_id, "speak"),
                               "reply_to": message["seq"]})
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
        "favorite": _favorite(),
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


# ---------- 御笔批注 ----------

MIN_NOTES_FOR_PATTERN = 3


def add_note(session_id: str, minister: str, text: str) -> dict:
    """皇帝把某位大臣的一句话收进御笔批注。

    落 turn 表而不是浏览器：批注的价值在跨局 —— 攒够了才看得出「你总是收藏谁」。
    记成皇帝的一行（minister="emperor"、target=那位大臣），所以它不会进评估的分母，
    也不会被当成一次发言算进回合。
    """
    if store.get_session(session_id) is None:
        raise KeyError(session_id)
    if minister not in roster.ROSTER:
        raise ValueError(minister)
    store.add_turn(session_id, "emperor", "note", "undecided",
                   text.strip()[:200], influence=0.0, target=minister)
    return snapshot(session_id)


def _favorite() -> dict | None:
    """跨局模式：你总是收藏谁的发言。

    少于 3 条批注不算模式 —— 一两条是巧合，不是倾向，这时返回 None。
    空就显示空，不编造：这条和确认率一样，第一次用的时候它本来就该是空的。
    """
    rows = store.note_counts()
    total = sum(r["n"] for r in rows)
    if total < MIN_NOTES_FOR_PATTERN:
        return None
    top = rows[0]
    return {"minister": top["minister"], "n": top["n"], "total": total,
            "share": round(top["n"] / total, 4)}


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
        "fallback": any(t["fallback"] for t in store.list_traces(session_id)
                        if t["op"] in ("stance", "speak", "reply", "verdict")),
        "factors": s.get("factors", []), "alliances": _alliances(s["turns"]),
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
