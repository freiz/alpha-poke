"""A language model's write-ups of a review (2026-10-30): an OpenAI-compatible chat model, set on
the home page (its base URL, key and model kept in the data directory's llm.json, the key never
sent back to a page), given the review's facts (coach.packet) and told to use only them. Kinds:
"style" -- how the player played (habits, with the turns and numbers that show them, and what to
practise); "team" -- the player's team (its make-up, strengths, weaknesses, what this game showed,
suggestions within its common sets); "turn" -- one decision explained, or a question about it
answered. Each write-up is kept with its review (llm-<kind>[-<decision>[-<question>]].<lang>.md):
opened again it costs nothing. Every move it names, in English or Chinese, is checked against the two teams' learnsets
and the moves used in the game; an unknown one gets a warning appended."""

import hashlib
import json
import os
import re
from pathlib import Path

import requests

from alpha_poke.analysis.roles import to_id
from alpha_poke.coach import packet
from alpha_poke.coach.personas import (  # noqa: F401 - (PERSONAS: the settings' choices)
    DEFAULT_PERSONA,
    PERSONAS,
    persona_prompt,
    reminder,
    signature,
)
from alpha_poke.dex import GEN, learnset

KINDS = ("style", "team", "turn")

RULES = {
    "zh": """规则：
- 只能使用数据包里的事实和数字。不要编造招式、道具、特性、配置或对局中没发生的事；数据包里没有的就说不知道。
- 宝可梦、招式、道具、特性、属性一律用 names_zh 里的官方中文名；第一次提到时在括号里附英文名，例如 保姆曼波（Alomomola）。
- AI 的数字是几秒钟搜索得出的估计：说“AI 认为……更好（胜率约 X% 对 Y%）”，X 是 ai_choice_win_chance（AI 的选择），Y 是 chosen_win_chance（玩家的选择）；
  position_win_chance 是这一步之前的局面胜率，不是哪个选项的。不要说某一步一定错了。差距不到 3 个百分点的不算失误；讲失误时按 loss 从大到小，最大的先讲。
- 太晶化之后，宝可梦挨打时只按太晶属性算相克（log 里 -terastallize 那一回合起），不要再按原来的属性算。
- kind 为 switch after a faint 时，倒下的是哪只看 log 里那一回合的 faint 行，ME 是玩家、OPP 是对手，不要弄混。
- verdict 的含义：same 和 AI 一致，ok 可以接受，mild AI 不太喜欢，bad AI 不认同。
- guessed_moves 是没贴队伍时 AI 猜测的招式，玩家未必有，不要据此批评。
- 胜率的大起大落可能来自运气（会心一击、没命中、麻痹等，见 log）或对手没走 AI 预想的应对（opponent_expected 与 opponent_did）：不要把它们算成玩家的失误，
  也不要算成玩家的功劳。swings 是程序算好的胜率变化最大的几处（change 正为上升、负为下降），带着玩家那一步的损失 your_loss、
  对手实际的选择和 AI 最预计的应对各自对应的玩家胜率、那几回合 log 里的运气（luck_in_log：会心一击、没命中、不能动；ME 是玩家，OPP 是对手，看清是谁的运气）。
  讲到胜率大幅上升或下降（相邻决策的 position_win_chance 变化 15 个百分点以上，swings 里都有）时，先找原因：
  看那一步 opponent_did 在 opponent_expected 里对应的 your_win_chance，和 AI 最预计的应对比，差得多就是对手的选择带来的（对手失误或妙手）；
  opponent_did_unexpected 为 true 时 AI 没料到这一手、没有对应的数字，就看下一个决策的 position_win_chance 变了多少；
  log 里有会心一击、没命中等就是运气；都不是才是玩家自己打出来的。逆转或翻车要如实说清是谁、哪一回合造成的。
- 解释“为什么”时，用数据包里的事实：属性相克（takes）、速度（种族值 base.spe）、道具、特性、能力变化、场地。
- 每个结论都要引用具体回合，例如“第 35 回合”。""",
    "en": """Rules:
- Use only the facts and numbers in the data. Do not invent moves, items, abilities, sets or
  events; say you don't know what the data does not show.
- Name Pokémon, moves, items, abilities and types in English exactly as the data does.
- The AI's numbers are estimates from a few seconds of search: say "the AI thought ... was better
  (about X% vs Y% to win)" -- X the ai_choice_win_chance, Y the chosen_win_chance (the
  position_win_chance is the position's before the move, no option's) -- never that a move was
  certainly wrong. A gap under 3 points is no mistake; take the mistakes by loss, largest first.
- A terastallized Pokémon takes hits by its tera type alone (from the turn of its -terastallize
  in the log), not its old types.
- For a "switch after a faint", which one fainted is the log's faint line of that turn (ME the
  player, OPP the opponent): do not mix them up.
- verdict: same = the AI's own choice, ok = acceptable, mild = the AI doesn't like it, bad = the
  AI disagrees.
- guessed_moves are the AI's guesses of the player's moves (no team pasted): the player may not
  have them; do not criticize on them.
- Big swings can come from luck (critical hits, misses, full paralysis: see the log) or from the
  opponent not playing what the AI expected (opponent_expected vs opponent_did): count them
  neither as the player's mistakes nor as the player's credit. swings lists the largest moves
  (change > 0 up, < 0 down) with the player's loss there (your_loss), the player's chance after
  the opponent's actual reply and after the AI's most expected one, and the luck in those turns'
  log (luck_in_log: crits, misses, full paralysis -- ME the player, OPP the opponent: whose luck).
  When the chance rises or falls a lot (position_win_chance moving 15 points or more between
  decisions, all in swings), find the cause first:
  the your_win_chance of opponent_did in opponent_expected against the AI's most expected reply
  -- far apart: the opponent's choice did it (a mistake or a good play; opponent_did_unexpected:
  a reply the AI did not weigh, no number -- see how the next decision's position_win_chance
  moved); a crit or miss in the
  log: luck; neither: the player's own play. Say plainly who turned the game, and on which turn.
- Explain *why* with the data's facts: type matchups (takes), speed (base.spe), items, abilities,
  boosts, the field.
- Back every point with the turns it comes from, e.g. "turn 35".""",
}

SYSTEMS = {
    "style": {
        "zh": """你是宝可梦 Showdown 第九世代 OU 的教练，在给一位热血的宝可梦爱好者讲这一局的操作风格（数据里的 you / 玩家就是这位爱好者）。
你会收到这局的 JSON 数据包：双方队伍（you = 玩家，opponent = 对手）、逐回合日志（ME = 玩家，OPP = 对手）、
玩家每个决策时一个强力搜索 AI 的看法（各选项的胜率估计 win_chance 和思考比例 share、AI 的选择 ai_choice、
损失 loss、判定 verdict、AI 预计的对手应对和对手实际的选择、AI 预想的走向 ai_lines），以及中英文名对照 names_zh。
opponent_archetype 是从对手亮出的部分猜的对手流派（style 风格、features 特色、about 打法和一般的克制方法），只是猜测，讲到时说“看起来像”。
{rules}
用简体中文写，亲切、具体、通俗（玩家可能是孩子也可能是老手：说法要让谁都听得懂），不超过 900 字。分五节：
1. 总体风格（2-3 句：这局是怎么打的，偏进攻还是稳健，换人多不多，太晶用在哪）
2. 这局的转折点（1-3 个胜率变化最大的地方，按变化大小排：哪一回合、胜率从多少到多少、原因是玩家的选择、对手的失误或妙手、还是运气；
   双方最大的失误都要在这里，赢了也要说清有没有靠对手送或运气）
3. 做得好的地方（2-3 点，每点有回合和数字；只算玩家自己打出来的）
4. 可以改进的习惯（2-4 点：一个反复出现的模式，哪几个回合，AI 当时更想怎么做以及为什么）
5. 下次可以练习（2-3 条具体建议）""",
        "en": """You are a Pokémon Showdown Gen 9 OU coach, telling a passionate Pokémon fan about their playing style in
one game. You get the game's data as JSON: both teams (you = the player, opponent), the
turn-by-turn log (ME = the player, OPP = the opponent), and for each of the player's decisions a
strong search AI's view (each option's estimated win_chance and its share of the AI's thinking,
the AI's choice ai_choice, the loss, the verdict, the opponent's reply the AI expected and what
the opponent did, the AI's expected lines ai_lines). opponent_archetype is the opponent's
archetype guessed from what it revealed (style, features, about: how it plays and is beaten in
general) -- a guess: say "looks like".
{rules}
Write in English, friendly and concrete, plain enough for any player (a child or a veteran), under 600 words. Five sections:
1. Overall style (2-3 sentences: how the game was played -- aggressive or careful, many
   switches or few, where tera went)
2. The turning points (1-3 of the largest swings of the chance, largest first: the turn, the
   chance from and to, and the cause -- the player's choice, the opponent's mistake or good
   play, or luck; both sides' biggest mistakes belong here, and a win the opponent or luck
   handed over is said so)
3. What went well (2-3 points, each with turns and numbers; only what the player's own play did)
4. Habits to work on (2-4 points: a pattern that came up more than once, the turns, what the AI
   preferred and why)
5. What to practise next (2-3 concrete suggestions)""",
    },
}


SYSTEMS["team"] = {
    "zh": """你是宝可梦 Showdown 第九世代 OU 的教练，在帮一位热血的宝可梦爱好者分析这一局用的队伍（数据里的 you / 玩家就是这位爱好者）。
你会收到 JSON 数据包：双方队伍（you = 玩家）、team_facts（各攻击属性打过来时队里谁怕谁抗、已知招式能克制哪些属性、
速度对比、招式起的作用 roles 和缺少的作用 roles_missing、玩家每只宝可梦在天梯上的常见配置 your_common_sets、
天梯上最常见的宝可梦 ladder_top）、这一局的日志和每个决策的数据，以及中英文名对照 names_zh。
your_team_pasted 为 false 时，玩家的配置只有这局亮出来的部分，没亮出的不要当成没有。
{rules}
- team_facts.metagame 是从几十万场天梯对局和论坛队伍整理的环境数据（只看宝可梦种类，不看配置）：
  expected_vs_metagame 是对局模型估计的、对近期环境的平均胜率，worst_20pct_of_metagame 是最难打的那 20% 对手下的胜率；
  threats_worst 是最怕的热门宝可梦；members 里有每只的强度排名、常见克星 checks_and_counters、常见队友；
  cores 是队里两两组合在天梯上的场次、胜率和超出分数预期的部分；synergy 是对局模型学到的队友配合（两只放在一起比各自单独多出或少掉的胜率点数）；
  threat_coverage 是按配置做的伤害计算，覆盖出场率 0.05% 以上的所有宝可梦（占对手出场的 98%）：answered_share 是按出场频率算的、队里有人能硬接（check）
  或先手打倒（revenge）的对手宝可梦所占比例；unanswered 是谁也接不住的（按出场率排序）；one_answer 只有一只能应对；most_used 是最常见 15 只的完整结果；
  rare_counters 是出场率低于 0.5%、没人能接、还能一击打倒两只以上的冷门天敌；your_sets_exact 为 false 时玩家没亮出的配置是按常见配置推测的；
  counters_by_model 是对局模型看来专门克制这支队伍的宝可梦（不论热门与否，points_against_you 是对你的胜率点数）。
  archetype 是队伍的流派：style 是风格（受队/平衡/重攻/高速进攻，style_probs 是分类器的把握，它在论坛队伍上的准确率约四分之三，不确定时要说“偏向”），
  features 是特色（钉子、黏网、天气、戏法空间、双墙、轮转），about 是各流派的打法和一般的克制方法；metagame 里有每个流派在环境中的占比、
  超出分数预期的战绩、常见成员和克制它的宝可梦 answers（model_logit 是对局模型的估计，games_lift 是对局数据里的实际表现、games 是场次，两者一致才可信）；
  your_score_by_opponent_style 是这支队伍面对各风格对手的预计胜率，style_vs_style 是这种风格对其他风格的历史表现。
- 讲威胁时把常见威胁和冷门天敌分开：常见威胁（出场率高）要优先想办法解决；冷门天敌讲清楚遇到时怎么应对就行，不必为它改队。swaps 是把一只换成另一只热门宝可梦后模型估计的变化，
  只是线索（模型看不到配置、分工和配合），提到时要说明这一点；similar_teams 是论坛或天梯上相似的队伍和它们不一样的地方（论坛队伍注意 date：太旧的可能不适合现在的环境）。
  这些数字是统计结果，场次少的不要下结论，天梯胜率里也有玩家水平的因素。
- 建议改配置时，只能用 your_common_sets 或 similar_teams 里出现的招式、道具、太晶属性、特性，并说明为什么有用；建议换宝可梦要谨慎，说清楚取舍。
用简体中文写，亲切、具体、通俗（玩家可能是孩子也可能是老手：说法要让谁都听得懂），不超过 900 字。分五节：
1. 队伍构成（每只大概担任什么角色）
2. 优点（2-3 点）
3. 弱点（属性弱点是否集中、速度、缺少的作用等，用 team_facts 的数据说明）
4. 这一局暴露的问题（引用回合）
5. 建议（2-4 条，具体）""",
    "en": """You are a Pokémon Showdown Gen 9 OU coach helping a passionate Pokémon fan understand the team they used in
one game. You get JSON: both teams (you = the player), team_facts (which of the team each
attacking type hits hard or is resisted by, the types its known attacks hit super effectively,
speeds, the roles its moves fill and roles_missing, the player's species' common sets on the
ladder your_common_sets, the ladder's most used species ladder_top), this game's log and every
decision's numbers. If your_team_pasted is false the player's sets are only what this game
showed: do not take an unshown part as missing.
{rules}
- team_facts.metagame is the metagame's view from hundreds of thousands of ladder games and the
  forum's teams, by species only (no sets): expected_vs_metagame is the matchup model's mean chance
  against the recent metagame, worst_20pct_of_metagame its chance against the hardest fifth;
  threats_worst the popular species it fears most; members each one's strength rank, its checks
  and counters and usual teammates; cores the team's pairs on the ladder (games, win rate, margin
  over the ratings' expectation); synergy the matchup model's teammate term (points of winning
  chance two bring together beyond each alone); threat_coverage the damage calculation set by set
  over every species with a share >= 0.05% (98% of the opponents' Pokemon): answered_share the
  share of the opponents' Pokemon the team checks or revenge-kills, unanswered the ones nobody
  answers (by share), one_answer, most_used the 15 most used in full, rare_counters rare ones
  (share < 0.5%) nobody answers that KO two or more of the team (your_sets_exact false: the
  player's unshown parts are the common set's guess); counters_by_model the species the matchup
  model sees countering this team in particular, however rare (points_against_you);
  archetype the team's archetype: its style (stall / balance / bulky offense / hyper offense;
  style_probs the classifier's confidence -- about three in four right on the forum's teams: say
  "leans" when unsure), its features (hazard stack, webs, weather, Trick Room, screens,
  volt-turn), about how each plays and is beaten in general; metagame per archetype its share,
  record (margin over the ratings), usual members and answers (model_logit the matchup model's,
  games_lift what the games show, games how many: trust an answer when both agree);
  your_score_by_opponent_style the team's expected chance against each style; style_vs_style
  its style's record against the others;
  swaps the model's change when one member is replaced by a
  popular species -- leads only (the model sees no sets, roles or synergy): say so when you use
  them; similar_teams the forum's and the ladder's teams like this one and what they run instead
  (a forum team's date: an old one may not fit today's metagame).
  These are statistics: do not conclude from few games; ladder records are their players' too.
- Keep common threats and rare counters apart: the common ones (high share) are worth fixing the
  team for; for a rare counter say how to play it, without rebuilding the team around it.
- Suggest set changes only from your_common_sets or similar_teams (moves, items, tera types,
  abilities) and say why each helps; suggest replacing a Pokémon only carefully, with the trade-off.
Write in English, friendly and concrete, plain enough for any player (a child or a veteran), under 600 words. Five sections:
1. The team (each member's rough role)
2. Strengths (2-3)
3. Weaknesses (stacked type weaknesses, speed, missing roles -- with team_facts' data)
4. What this game exposed (with turns)
5. Suggestions (2-4, concrete)""",
}

SYSTEMS["turn"] = {
    "zh": """你是宝可梦 Showdown 第九世代 OU 的教练，在给一位热血的宝可梦爱好者讲这局里的某一步（数据里的 you / 玩家就是这位爱好者）。
你会收到 JSON 数据包：双方队伍、这一回合和前两回合的日志、这一步的数据 decision（玩家的选择 chosen、
各选项的胜率估计和 AI 思考比例、AI 的选择、判定、当时的场面 state、AI 预计的对手应对 opponent_expected
和对手实际的选择 opponent_did、AI 预想的走向 ai_lines），以及中英文名对照 names_zh。
{rules}
用简体中文写，亲切、具体，不超过 350 字。如果有玩家的提问，就直接回答这个问题；没有的话，讲清楚：
当时的局面、玩家的选择和 AI 的看法、AI 为什么这样看（对手可能怎么应对、接下来会怎样）、这一步可以学到什么。""",
    "en": """You are a Pokémon Showdown Gen 9 OU coach explaining one decision of a game to a passionate Pokémon fan.
You get JSON: both teams, the log of this turn and the two before, the decision (the player's
choice chosen, each option's estimated win_chance and the AI's share of thinking, the AI's
choice, the verdict, the public state, the opponent's replies the AI expected and what it did,
the AI's expected lines ai_lines).
{rules}
Write in English, friendly and concrete, under 200 words. If the player asks a question, answer
it; otherwise explain the position, the player's choice and the AI's view, why the AI sees it so
(how the opponent could reply, what happens next), and what to learn from it.""",
}


def settings_path(coach: Path) -> Path:
    return coach / "llm.json"


def load_settings(coach: Path) -> dict:
    """{base_url, api_key, model} (empty strings when not set), persona (PERSONAS; Cynthia when
    not set)."""
    try:
        s = json.loads(settings_path(coach).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    out = {k: str(s.get(k) or "") for k in ("base_url", "api_key", "model")}
    out["persona"] = s.get("persona") if s.get("persona") in PERSONAS else DEFAULT_PERSONA
    return out


def public_settings(coach: Path) -> dict:
    """What a page may see: the URL, the model, whether a key is set -- never the key --, the
    persona and the personas to choose from ([id, English name, Chinese name, English title,
    Chinese title]; "none": no role)."""
    s = load_settings(coach)
    return {"base_url": s["base_url"], "model": s["model"], "has_key": bool(s["api_key"]),
            "persona": s["persona"],
            "personas": [[k, *(p["name"] if p else ("No role", "不扮演角色")), *(p["title"] if p else ("", ""))]
                         for k, p in PERSONAS.items()]}  # fmt: skip


def save_settings(coach: Path, base_url: str, model: str, api_key: str | None,
                  persona: str | None = None) -> None:  # fmt: skip
    """``api_key`` None or empty: the one set before is kept; ``persona`` None or unknown too."""
    s = load_settings(coach)
    s["base_url"], s["model"] = base_url.strip(), model.strip()
    if persona in PERSONAS:
        s["persona"] = persona
    if api_key:
        s["api_key"] = api_key.strip()
    p = settings_path(coach)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s), encoding="utf-8")
    try:
        os.chmod(p, 0o600)  # (the key: this user's only)
    except OSError:
        pass


def chat(
    settings: dict, system: str, user: str, timeout: float = 300, messages: list | None = None
) -> str:
    """One answer of the configured chat model (OpenAI's /chat/completions); ``messages``: a
    conversation after the system prompt (user / assistant turns) instead of ``user`` alone."""
    if not (settings["base_url"] and settings["api_key"] and settings["model"]):
        raise RuntimeError("no_llm")
    r = requests.post(
        settings["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {settings['api_key']}", "Content-Type": "application/json"},
        json={"model": settings["model"], "temperature": 0.3,
              "messages": [{"role": "system", "content": system},
                           *(messages or [{"role": "user", "content": user}])]},
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
    names = packet.zh_names()
    zh = names["moves"]
    # (a move's Chinese name inside a Pokemon's, an item's or an ability's is not the move: 王牌,
    # Trump Card, in 闪焰王牌, Cinderace -- those names masked first, the longest first)
    masked = text
    others = {
        v for k in ("pokemon", "items", "abilities") for v in names[k].values() if len(v) >= 2
    }
    for other in sorted(others, key=len, reverse=True):
        if other in masked and other not in zh.values():
            masked = masked.replace(other, "\0")
    found = set()
    for mid, mv in GEN.moves.items():
        name = mv.get("name") or ""
        if len(name) > 4 and re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", text):
            found.add(mid)
        if len(zh.get(mid, "")) >= 2 and zh[mid] in masked:
            found.add(mid)
    bad = found - allowed
    # (a Chinese name inside a longer one the text names -- 冲浪 in 冲浪板 -- is that one's)
    bad = {m for m in bad if not any(zh.get(m) and zh.get(m) != zh.get(o) and zh[m] in zh.get(o, "")
                                     for o in found)}  # fmt: skip
    return sorted(GEN.moves[m].get("name", m) for m in bad)


def _file(review_dir: Path, kind: str, lang: str, dec: int | None, question: str | None) -> Path:
    name = f"llm-{kind}"
    if kind == "turn":
        name += f"-{int(dec)}"
        if question:
            name += "-" + hashlib.sha1(question.encode()).hexdigest()[:10]
    return review_dir / f"{name}.{lang}.md"


def _questions(review_dir: Path, dec: int, lang: str) -> Path:
    """A decision's asked questions (their hash -> the question: the answers' file names keep only
    the hash)."""
    return review_dir / f"llm-turn-{int(dec)}.{lang}.questions.json"


def answers(review_dir: Path, dec: int, lang: str) -> list[dict]:
    """Every answer kept for the ``dec``-th decision in ``lang``, oldest first: {"question" (None:
    the default explanation; "" when asked before the questions were kept), "text"}."""
    try:
        asked = json.loads(_questions(review_dir, dec, lang).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        asked = {}
    files = [review_dir / f"llm-turn-{int(dec)}.{lang}.md",
             *review_dir.glob(f"llm-turn-{int(dec)}-*.{lang}.md")]  # fmt: skip
    out = []
    for f in sorted((f for f in files if f.is_file()), key=lambda f: f.stat().st_mtime):
        sha = f.name.split(".")[0].split("-")[3] if f.name.count("-") >= 3 else None
        out.append({"question": None if sha is None else asked.get(sha, ""),
                    "text": f.read_text(encoding="utf-8")})  # fmt: skip
    return out


def asked(review_dir: Path, lang: str) -> dict[int, int]:
    """Decision index -> how many questions and answers are kept for it in ``lang`` (its thread)."""
    decs = {f.name.split(".")[0].split("-")[2] for f in review_dir.glob(f"llm-turn-*.{lang}.md")}
    decs |= {
        f.name.split(".")[0].split("-")[2] for f in review_dir.glob(f"llm-thread-*.{lang}.json")
    }
    return {int(d): n for d in decs if d.isdigit() and (n := len(thread(review_dir, int(d), lang)))}


# "ask the AI" as a conversation per decision (2026-10-30, the review page's side panel): the
# player's questions and the coach's answers, follow-ups with the whole conversation before them
DEFAULT_QUESTION = {"zh": "AI 为什么这样看这一步？", "en": "Why does the AI see this decision so?"}
THREAD = {
    "zh": "\n这是一段关于这一步的对话：像聊天一样直接回答玩家最新的问题，可以接着前面说过的内容，不重复已经讲过的；"
    "一般不超过 300 字；不用每次都总结或勉励，也不要署名。",
    "en": "\nThis is a conversation about this decision: answer the player's latest question directly, as "
    "in a chat, building on what was said and not repeating it; usually under 200 words; no summary "
    "or encouragement each time, and no signature.",
}


def _thread_file(review_dir: Path, dec: int, lang: str) -> Path:
    return review_dir / f"llm-thread-{int(dec)}.{lang}.json"


def thread(review_dir: Path, dec: int, lang: str) -> list[dict]:
    """The ``dec``-th decision's conversation in ``lang``: [{"question", "answer", "coach" ([en,
    zh] name or None)}], the answers kept before the conversations first (answers: question None
    the default explanation, "" one whose words were not kept)."""
    out = [{"question": a["question"], "answer": a["text"], "coach": None}
           for a in answers(review_dir, dec, lang)]  # fmt: skip
    try:
        out += json.loads(_thread_file(review_dir, dec, lang).read_text(encoding="utf-8"))[
            "messages"
        ]
    except (OSError, ValueError, KeyError):
        pass
    return out


def clear_thread(review_dir: Path, dec: int, lang: str) -> None:
    """The ``dec``-th decision's conversation in ``lang`` deleted (and its earlier answers)."""
    for f in [_thread_file(review_dir, dec, lang), _questions(review_dir, dec, lang),
              review_dir / f"llm-turn-{int(dec)}.{lang}.md", *review_dir.glob(f"llm-turn-{int(dec)}-*.{lang}.md")]:  # fmt: skip
        f.unlink(missing_ok=True)


def ask(review_dir: Path, report: dict, row: dict, team: dict | None, dec: int, lang: str,
        settings: dict, question: str | None = None) -> dict:  # fmt: skip
    """The coach's answer to ``question`` (None: DEFAULT_QUESTION) about the ``dec``-th decision,
    after the conversation so far (the decision's facts with the first question), appended to
    the conversation and returned ({"question", "answer", "coach"})."""
    lang = "zh" if lang == "zh" else "en"
    if not 0 <= int(dec) < len(report["decisions"]):
        raise ValueError("no such decision")
    question = (question or "").strip()[:500] or DEFAULT_QUESTION[lang]
    data = packet.turn(report, row, team, int(dec))
    _archetype_notes(data, lang)
    persona = settings.get("persona", DEFAULT_PERSONA)
    system = (persona_prompt(persona, lang, chat=True) + SYSTEMS["turn"][lang].replace("{rules}", RULES[lang])
              + THREAD[lang])  # fmt: skip
    before = thread(review_dir, dec, lang)
    label = "\n\n玩家的提问：" if lang == "zh" else "\n\nThe player's question: "
    messages = []
    for i, m in enumerate([*before, {"question": question, "answer": None}]):
        q = m["question"] or DEFAULT_QUESTION[lang]
        messages.append(
            {"role": "user", "content": (packet.text(data) + label if i == 0 else "") + q}
        )
        if m["answer"] is not None:
            messages.append({"role": "assistant", "content": m["answer"]})
    messages[-1]["content"] += reminder(persona, lang)
    text = chat(settings, system, "", messages=messages).rstrip()
    bad = unknown_moves(text, report)
    if bad:
        text += ("\n\n> 校验提示：这段文字提到的这些招式，双方宝可梦都学不会，对局中也没有出现，可能是模型写错了："
                 if lang == "zh" else
                 "\n\n> Check: these moves the text names are not learnable by either team nor used in the game -- "
                 "likely the model's mistake: ") + ", ".join(bad) + "\n"  # fmt: skip
    p = PERSONAS.get(persona)
    m = {"question": question, "answer": text, "coach": list(p["name"]) if p else None}
    f = _thread_file(review_dir, dec, lang)
    try:
        kept = json.loads(f.read_text(encoding="utf-8"))["messages"]
    except (OSError, ValueError, KeyError):
        kept = []
    f.write_text(json.dumps({"messages": [*kept, m]}, ensure_ascii=False), encoding="utf-8")
    return m


def cached(review_dir: Path, kind: str, lang: str, dec: int | None = None,
           question: str | None = None) -> str | None:  # fmt: skip
    f = _file(review_dir, kind, lang, dec, question)
    return f.read_text(encoding="utf-8") if f.is_file() else None


def _archetype_notes(data: dict, lang: str) -> None:
    """The archetypes named in the facts, described in ``lang`` (teams.archetypes.ABOUT)."""
    from alpha_poke.teams import archetypes

    for d in (
        data.get("opponent_archetype"),
        ((data.get("team_facts") or {}).get("metagame") or {}).get("archetype"),
    ):
        if d:
            d["about"] = archetypes.notes(d, lang)


def write(review_dir: Path, report: dict, row: dict, team: dict | None, kind: str, lang: str,
          settings: dict, dec: int | None = None, question: str | None = None) -> str:  # fmt: skip
    """The ``kind`` write-up of a review in ``lang`` ("zh" / "en"), kept with it; "turn": the
    ``dec``-th decision's, ``question`` the player's own (else the default explanation)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    lang = "zh" if lang == "zh" else "en"
    question = (question or "").strip()[:500] or None
    if kind == "turn":
        if dec is None or not 0 <= int(dec) < len(report["decisions"]):
            raise ValueError("no such decision")
        data = packet.turn(report, row, team, int(dec))
    else:
        data = (packet.team(report, row, team, review_dir) if kind == "team"
                else packet.build(report, row, team))  # fmt: skip
    _archetype_notes(data, lang)
    persona = settings.get("persona", DEFAULT_PERSONA)
    # (the persona's card first, the coach's prompt and rules after it; its voice recalled last)
    system = persona_prompt(persona, lang) + SYSTEMS[kind][lang].replace("{rules}", RULES[lang])
    user = packet.text(data)
    if question:
        user += ("\n\n玩家的提问：" if lang == "zh" else "\n\nThe player's question: ") + question
    user += reminder(persona, lang)
    text = chat(settings, system, user).rstrip() + signature(persona, lang)
    bad = unknown_moves(text, report)
    if bad:
        text += ("\n\n> 校验提示：这段文字提到的这些招式，双方宝可梦都学不会，对局中也没有出现，可能是模型写错了："
                 if lang == "zh" else
                 "\n\n> Check: these moves the text names are not learnable by either team nor used in the game -- "
                 "likely the model's mistake: ") + ", ".join(bad) + "\n"  # fmt: skip
    _file(review_dir, kind, lang, dec, question).write_text(text, encoding="utf-8")
    if kind == "turn" and question:  # (the question itself kept: answers shows it with its answer)
        q = _questions(review_dir, dec, lang)
        try:
            asked = json.loads(q.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            asked = {}
        asked[hashlib.sha1(question.encode()).hexdigest()[:10]] = question
        q.write_text(json.dumps(asked, ensure_ascii=False), encoding="utf-8")
    return text
