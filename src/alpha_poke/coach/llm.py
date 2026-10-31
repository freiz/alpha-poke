"""A language model's write-ups of a review (2026-10-30): an OpenAI-compatible chat model, set on
the home page (its base URL, key and model kept in the data directory's llm.json, the key never
sent back to a page), given the review's facts (coach.packet) and told to use only them. Kinds:
"style" -- how the player played (habits, with the turns and numbers that show them, and what to
practise). Each write-up is kept with its review (llm-<kind>.<lang>.md): opened again it costs
nothing. Every move it names, in English or Chinese, is checked against the two teams' learnsets
and the moves used in the game; an unknown one gets a warning appended."""

import json
import os
import re
from pathlib import Path

import requests

from alpha_poke.analysis.roles import to_id
from alpha_poke.coach import packet
from alpha_poke.dex import GEN, learnset

KINDS = ("style",)

RULES = {
    "zh": """规则：
- 只能使用数据包里的事实和数字。不要编造招式、道具、特性、配置或对局中没发生的事；数据包里没有的就说不知道。
- 宝可梦、招式、道具、特性、属性一律用 names_zh 里的官方中文名；第一次提到时在括号里附英文名，例如 保姆曼波（Alomomola）。
- AI 的数字是几秒钟搜索得出的估计：说“AI 认为……更好（胜率约 X% 对 Y%）”，不要说某一步一定错了。差距不到 3 个百分点的不算失误。
- verdict 的含义：same 和 AI 一致，ok 可以接受，mild AI 不太喜欢，bad AI 不认同。
- guessed_moves 是没贴队伍时 AI 猜测的招式，玩家未必有，不要据此批评。
- 胜率的大起大落可能来自运气（会心一击、没命中、麻痹等，见 log）或对手没走 AI 预想的应对（opponent_expected 与 opponent_did）：不要把它们算成玩家的失误。
- 解释“为什么”时，用数据包里的事实：属性相克（takes）、速度（种族值 base.spe）、道具、特性、能力变化、场地。
- 每个结论都要引用具体回合，例如“第 35 回合”。""",
    "en": """Rules:
- Use only the facts and numbers in the data. Do not invent moves, items, abilities, sets or
  events; say you don't know what the data does not show.
- Name Pokémon, moves, items, abilities and types in English exactly as the data does.
- The AI's numbers are estimates from a few seconds of search: say "the AI thought ... was better
  (about X% vs Y% to win)", never that a move was certainly wrong. A gap under 3 points is no
  mistake.
- verdict: same = the AI's own choice, ok = acceptable, mild = the AI doesn't like it, bad = the
  AI disagrees.
- guessed_moves are the AI's guesses of the player's moves (no team pasted): the player may not
  have them; do not criticize on them.
- Big swings can come from luck (critical hits, misses, full paralysis: see the log) or from the
  opponent not playing what the AI expected (opponent_expected vs opponent_did): do not count
  them as the player's mistakes.
- Explain *why* with the data's facts: type matchups (takes), speed (base.spe), items, abilities,
  boosts, the field.
- Back every point with the turns it comes from, e.g. "turn 35".""",
}

SYSTEMS = {
    "style": {
        "zh": """你是宝可梦 Showdown 第九世代 OU 的教练，在给一位小朋友讲他这一局的操作风格。
你会收到这局的 JSON 数据包：双方队伍（you = 玩家，opponent = 对手）、逐回合日志（ME = 玩家，OPP = 对手）、
玩家每个决策时一个强力搜索 AI 的看法（各选项的胜率估计 win_chance 和思考比例 share、AI 的选择 ai_choice、
损失 loss、判定 verdict、AI 预计的对手应对和对手实际的选择、AI 预想的走向 ai_lines），以及中英文名对照 names_zh。
{rules}
用简体中文写，亲切、具体、适合小朋友，不超过 800 字。分四节：
1. 总体风格（2-3 句：这局是怎么打的，偏进攻还是稳健，换人多不多，太晶用在哪）
2. 做得好的地方（2-3 点，每点有回合和数字）
3. 可以改进的习惯（2-4 点：一个反复出现的模式，哪几个回合，AI 当时更想怎么做以及为什么）
4. 下次可以练习（2-3 条具体建议）""",
        "en": """You are a Pokémon Showdown Gen 9 OU coach, telling a young player about their playing style in
one game. You get the game's data as JSON: both teams (you = the player, opponent), the
turn-by-turn log (ME = the player, OPP = the opponent), and for each of the player's decisions a
strong search AI's view (each option's estimated win_chance and its share of the AI's thinking,
the AI's choice ai_choice, the loss, the verdict, the opponent's reply the AI expected and what
the opponent did, the AI's expected lines ai_lines).
{rules}
Write in English, friendly and concrete for a child, under 500 words. Four sections:
1. Overall style (2-3 sentences: how the game was played -- aggressive or careful, many
   switches or few, where tera went)
2. What went well (2-3 points, each with turns and numbers)
3. Habits to work on (2-4 points: a pattern that came up more than once, the turns, what the AI
   preferred and why)
4. What to practise next (2-3 concrete suggestions)""",
    },
}


def settings_path(coach: Path) -> Path:
    return coach / "llm.json"


def load_settings(coach: Path) -> dict:
    """{base_url, api_key, model} (empty strings when not set)."""
    try:
        s = json.loads(settings_path(coach).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    return {k: str(s.get(k) or "") for k in ("base_url", "api_key", "model")}


def public_settings(coach: Path) -> dict:
    """What a page may see: the URL, the model, whether a key is set -- never the key."""
    s = load_settings(coach)
    return {"base_url": s["base_url"], "model": s["model"], "has_key": bool(s["api_key"])}


def save_settings(coach: Path, base_url: str, model: str, api_key: str | None) -> None:
    """``api_key`` None or empty: the one set before is kept."""
    s = load_settings(coach)
    s["base_url"], s["model"] = base_url.strip(), model.strip()
    if api_key:
        s["api_key"] = api_key.strip()
    p = settings_path(coach)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s), encoding="utf-8")
    try:
        os.chmod(p, 0o600)  # (the key: this user's only)
    except OSError:
        pass


def chat(settings: dict, system: str, user: str, timeout: float = 300) -> str:
    """One answer of the configured chat model (OpenAI's /chat/completions)."""
    if not (settings["base_url"] and settings["api_key"] and settings["model"]):
        raise RuntimeError("no_llm")
    r = requests.post(
        settings["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {settings['api_key']}", "Content-Type": "application/json"},
        json={"model": settings["model"], "temperature": 0.3,
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
        timeout=timeout,
    )  # fmt: skip
    if r.status_code != 200:
        raise RuntimeError(f"the model's service answered {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def unknown_moves(text: str, report: dict) -> list[str]:
    """The moves the text names -- English or Showdown's Chinese names -- that neither team can
    learn and nobody used in the game (a model's invention)."""
    allowed: set[str] = set()
    for side in ("p1", "p2"):
        for m in report["teams"][side]:
            allowed |= learnset(m["species"]) or set()
            allowed |= {to_id(x) for x in m["moves"]}
    zh = packet.zh_names()["moves"]
    found = set()
    for mid, mv in GEN.moves.items():
        name = mv.get("name") or ""
        if len(name) > 4 and re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text):
            found.add(mid)
        if len(zh.get(mid, "")) >= 2 and zh[mid] in text:
            found.add(mid)
    bad = found - allowed
    # (a Chinese name inside a longer one the text names -- 冲浪 in 冲浪板 -- is that one's)
    bad = {m for m in bad if not any(zh.get(m) and zh.get(m) != zh.get(o) and zh[m] in zh.get(o, "")
                                     for o in found)}  # fmt: skip
    return sorted(GEN.moves[m].get("name", m) for m in bad)


def cached(review_dir: Path, kind: str, lang: str) -> str | None:
    f = review_dir / f"llm-{kind}.{lang}.md"
    return f.read_text(encoding="utf-8") if f.is_file() else None


def write(review_dir: Path, report: dict, row: dict, team: dict | None, kind: str, lang: str,
          settings: dict) -> str:  # fmt: skip
    """The ``kind`` write-up of a review in ``lang`` ("zh" / "en"), kept with it."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    lang = "zh" if lang == "zh" else "en"
    data = packet.build(report, row, team)
    system = SYSTEMS[kind][lang].replace("{rules}", RULES[lang])
    text = chat(settings, system, packet.text(data))
    bad = unknown_moves(text, report)
    if bad:
        text += ("\n\n> 校验提示：这段文字提到的这些招式，双方宝可梦都学不会，对局中也没有出现，可能是模型写错了："
                 if lang == "zh" else
                 "\n\n> Check: these moves the text names are not learnable by either team nor used in the game -- "
                 "likely the model's mistake: ") + ", ".join(bad) + "\n"  # fmt: skip
    (review_dir / f"llm-{kind}.{lang}.md").write_text(text, encoding="utf-8")
    return text
