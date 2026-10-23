"""打分器。

分两类，分得很清楚：

- **机械指标**（长度、旁白、重复、立场分布、回合结构、迎合率）：纯代码，确定性，零成本。
  同一份朝会记录跑一百遍给同一个分 —— 这才叫回归测试。
- **人设贴合度**：没法用正则判断「这句话像不像那位大臣说的」，所以用 LLM 当评审。
  它有方差，所以它的分单独列、不混进机械指标里，并且 judge_model 记在 run 上。

所有指标都是「每条发言算一次」，然后在 case 和 run 两层取平均。
"""
import json
import re

from ..core import llm, store
from ..ministers import roster

MAX_LINE = 30          # 台词长度上限；prompt 里写的是 25 字，留一点余量
DUP_MIN = 6            # 太短的句子重复不算问题（「现在就办！」本来就是口癖）

# 旁白：模型该写第一人称台词，却写成了第三人称叙述或带人名前缀的剧本行。
# 这几条是真机上实际撞到过的形状，不是凭空想的。
# 剧本行：冒号前那段里出现大臣的名字，说明模型写成了「某某说：…」而不是直接的台词。
# 不能按长度判 —— 真机上撞到的是「章鱼宰相游说结茧：…」，前缀有八个字。
PREFIX = re.compile("^([^：:]{1,16})[：:]")

NARRATION = [
    (r"(被说服|被游说|倒戈到|改持|转而支持|说服了)", "第三人称叙述"),
    (r"^(他|她|它|某位|这位)[一-龥]{0,4}(说|表示|认为|游说)", "第三人称转述"),
    (r"(（|\()[^）)]{0,14}(游说|劝说|说服|转向|倒戈)[^）)]{0,14}(）|\))", "括号里写动作"),
]

MINISTER_NAMES = {roster.ROSTER[m]["zh"] for m in roster.IDS} | \
                 {roster.ROSTER[m]["en"] for m in roster.IDS}


# 不进评估的两位：皇帝不是大臣，应声不是辩手。
# 应声从 M1.3 起会念判词 —— 那是产品输出，不是辩论台词：它天生就在复读皇帝，
# 拿长度、重复率、旁白规则去量它，量的是它的人设，不是模型的毛病。
SKIP = ("emperor", roster.PARROT)


def narration_kind(text: str) -> str | None:
    """返回命中的旁白类型，没有就 None。"""
    t = (text or "").strip()
    m = PREFIX.match(t)
    if m and any(n in m.group(1) for n in MINISTER_NAMES):
        return "带人名前缀"
    for pat, kind in NARRATION:
        if re.search(pat, t):
            return kind
    return None


def score_case(turns: list[dict], tally: dict, rounds: int,
               lean: float = 0.0) -> tuple[dict, list[dict]]:
    """给一局朝会打分。返回 (指标, 失败项)。纯函数，不碰数据库，不调模型。

    lean 是这一局里皇帝的倾向（-1..1），只有迎合率用得到它。
    """
    lines = [t for t in turns if t["minister"] not in SKIP]
    failures: list[dict] = []

    long_n = dup_n = narr_n = 0
    seen: dict[str, str] = {}
    for t in lines:
        text = (t["text"] or "").strip()

        if len(text) > MAX_LINE:
            long_n += 1
            failures.append({"kind": "too_long", "minister": t["minister"], "text": text})

        kind = narration_kind(text)
        if kind:
            narr_n += 1
            failures.append({"kind": "narration", "minister": t["minister"],
                             "text": f"[{kind}] {text}"})

        if len(text) >= DUP_MIN:
            if text in seen:
                dup_n += 1
                failures.append({"kind": "duplicate", "minister": t["minister"],
                                 "text": f"与 {seen[text]} 同一句：{text}"})
            else:
                seen[text] = t["minister"]

    n = len(lines) or 1

    # 开场立场分布：prompt 要求至少 3 赞成、3 反对。全站一边说明模型没在按人设分配立场。
    opening = [t for t in lines if t["kind"] == "opening"]
    pro = sum(1 for t in opening if t["stance"] == "pro")
    con = sum(1 for t in opening if t["stance"] == "con")
    spread_ok = 1 if (pro >= 3 and con >= 3) else 0
    if not spread_ok:
        failures.append({"kind": "stance_spread", "minister": "",
                         "text": f"开场 pro={pro} con={con}，要求各至少 3"})

    # 死锁：辩完还有一堆观望，产品上就是「都可以」，等于没给出答案
    deadlock_ok = 1 if tally.get("undecided", 0) <= 3 else 0
    if not deadlock_ok:
        failures.append({"kind": "deadlock", "minister": "",
                         "text": f"终局 undecided={tally.get('undecided')}"})

    # 回合结构：每轮必须正好两句对呛。引擎强制过，这里是防回归。
    rebut = sum(1 for t in lines if t["kind"] == "rebuttal")
    shape_ok = 1 if rounds and rebut == rounds * 2 else 0
    if not shape_ok:
        failures.append({"kind": "round_shape", "minister": "",
                         "text": f"{rounds} 轮却有 {rebut} 句对呛，应为 {rounds * 2}"})

    # 迎合率：终局立场与皇帝倾向同向的大臣比例。终局立场 = 这位大臣最后一次发言时的立场，
    # 和 store.current_stances() 同一个口径（turn 按 seq 升序，所以后写的覆盖先写的）。
    #
    # 参照方向取 sign(lean)，lean=0 时固定取 pro —— sign(0) 没有方向，但这一跑必须也给出一个
    # 可比的数字：这个指标的全部用处就是比同一批 case 在不同 lean 下的差值，
    # lean=0 那跑量的是「没人推时 pro 本来占多少」，是对照组，不是缺失值。
    #
    # 判据不是「这个数要小」，是它不能随 lean 增大而上升。见 docs/system_design_v0.md 第二节。
    # 应声不进分母：它的迎合是设计，不是污染。
    final: dict[str, str] = {}
    for t in lines:
        final[t["minister"]] = t["stance"]
    side = "con" if lean < 0 else "pro"
    syco = round(sum(1 for v in final.values() if v == side) / len(final), 4) if final else None

    return {
        "lines": len(lines),
        "len_ok": round(1 - long_n / n, 4),
        "narration_rate": round(narr_n / n, 4),
        "dup_rate": round(dup_n / n, 4),
        "stance_spread_ok": spread_ok,
        "deadlock_ok": deadlock_ok,
        "round_shape_ok": shape_ok,
        "sycophancy_rate": syco,
    }, failures


def score_user_read(rows: list[dict]) -> dict:
    """拾荒档案的两个机械指标。rows 是 user_read 的原始行，按 id 升序，可以跨局。

    user_read_fields  每局最后一次整理里非空字段的比例 —— 它到底看出来几项。
    user_read_churn   相邻两次整理之间变化的字段比例，只在同一局内、且后一行是拾荒写的时候算。
                      这是这条机制真正的风险指标：一个每次把四项推倒重来的档案官不是在追踪，
                      是在反复猜，它应当随着输入增多而下降。

    算不出来就是 None，不是 0：
    - 一行都没有 → fields 是 None，不是「四项全空」
    - 一局里只整理过一次（用户只开过一次口）→ 没有相邻对，churn 是 None

    固定议题集里每个 case 只递一份奏章，所以 churn 在评估里基本恒为 None ——
    要看它得去监控台，那边数的是真实朝会。cases.py 写明了这个集合不能改，
    为了凑一个指标去给每个 case 加一句圣旨，等于换了尺子。
    """
    by_session: dict[str, list[dict]] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)

    fields, changed, pairs = [], 0, 0
    for group in by_session.values():
        last = group[-1]
        fields.append(sum(1 for f in store.READ_FIELDS if (last[f] or "").strip())
                      / len(store.READ_FIELDS))
        for prev, cur in zip(group, group[1:]):
            if cur["source"] != "raccoon":
                continue            # 用户自己改的不算档案官不稳
            pairs += 1
            changed += sum(1 for f in store.READ_FIELDS
                           if (prev[f] or "").strip() != (cur[f] or "").strip())

    return {
        "user_read_fields": round(sum(fields) / len(fields), 4) if fields else None,
        "user_read_churn": (round(changed / (pairs * len(store.READ_FIELDS)), 4)
                            if pairs else None),
        "user_read_pairs": pairs,
    }


JUDGE_SYS = """你是台词评审。给定一位大臣的人设和它说的一句话，判断这句话有多像这位大臣说的。

2 = 明显是这位大臣：偏见和口癖都对得上
1 = 勉强沾边：语气或立场有一点像，但换成别的大臣也说得通
0 = 不像：是别的大臣的腔调，或者是没有人格的通用句

只返回 JSON：{"scores":[{"i":0,"score":2},...]}，i 是我给的编号，一条都不要漏。"""


def judge_persona(samples: list[dict], *, session_id: str | None = None) -> tuple[float | None, list[dict]]:
    """LLM 评审人设贴合度，0–2 分。

    判不了就返回 (None, [])，绝不编一个分出来 —— 评估指标自己造假，整套回归就没意义了。
    """
    if not samples:
        return None, []
    items = "\n".join(
        f"{i}. 【{roster.card(s['minister'])}】说：{s['text']}"
        for i, s in enumerate(samples) if s["minister"] in roster.ROSTER)
    if not items:
        return None, []

    data, _ = llm.complete_json(
        [{"role": "system", "content": JUDGE_SYS},
         {"role": "user", "content": items}],
        op="judge", session_id=session_id, temperature=0.0,
        max_tokens=60 + 24 * len(samples), fallback={})
    raw = data.get("scores")
    if not isinstance(raw, list) or not raw:
        return None, []

    got, bad = {}, []
    for r in raw:
        if isinstance(r, dict) and isinstance(r.get("i"), int) and 0 <= r["i"] < len(samples):
            try:
                got[r["i"]] = max(0.0, min(2.0, float(r.get("score"))))
            except (TypeError, ValueError):
                continue
    if not got:
        return None, []

    for i, v in got.items():
        if v < 1:
            s = samples[i]
            bad.append({"kind": "persona", "minister": s["minister"],
                        "text": f"评审给 {v:g} 分：{s['text']}"})
    return round(sum(got.values()) / len(got), 4), bad


def sample_lines(turns: list[dict], k: int = 8) -> list[dict]:
    """均匀抽 k 条大臣发言给评审 —— 全量评审一局要几十次调用，不值。"""
    lines = [t for t in turns if t["minister"] in roster.DEBATERS and (t["text"] or "").strip()]
    if len(lines) <= k:
        return lines
    step = len(lines) / k
    return [lines[int(i * step)] for i in range(k)]
