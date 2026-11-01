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
from urllib.parse import urlsplit

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
- “引擎”是这个程序自己的对战 AI（神经网络 + 搜索），数据包里的胜率和判断都来自它；你是教练，提到它时说“引擎”。
- 这一局的事实（招式、道具、特性、配置、发生了什么、数字）只能用数据包里的。不要编造招式、道具、特性、配置或对局中没发生的事；数据包里没有的就说不知道。
- 引擎的分析是模型给出的，不一定完美：胜率、判定、预计的对手应对和推演 ai_lines 都来自神经网络加几秒钟的搜索。它只往前看几回合，
  长期的东西（保住胜利手段、钉子和削血的累积价值、残局怎么收）可能看不全；对手没亮出的配置是它猜的；胜率有误差。
  把引擎当作最重要的参考，同时要有你自己作为教练的判断：结合宝可梦对战的一般知识（属性和对位、常见打法、胜利手段、节奏）去看这一局。
  你觉得引擎可能看漏了，或者你有不同看法时，可以说出来，但要讲清楚这是你的看法、理由是什么，和引擎的数字分开说；不要为了反驳而反驳。
  在合适的地方提醒一次引擎的判断不一定完美就够了，不要每段都重复。
- 宝可梦、招式、道具、特性、属性一律用 names_zh 里的官方中文名；第一次提到时在括号里附英文名，例如 保姆曼波（Alomomola）。
- 引擎的数字是几秒钟搜索得出的估计：说“引擎认为……更好（胜率约 X% 对 Y%）”，X 是 ai_choice_win_chance（引擎的选择），Y 是 chosen_win_chance（玩家的选择）；
  position_win_chance 是这一步之前的局面胜率，不是哪个选项的。不要说某一步一定错了。差距不到 3 个百分点的不算失误；讲失误时按 loss 从大到小，最大的先讲。
- 太晶化之后，宝可梦挨打时只按太晶属性算相克（log 里 -terastallize 那一回合起），不要再按原来的属性算。
- kind 为 switch after a faint 时，倒下的是哪只看 log 里那一回合的 faint 行，ME 是玩家、OPP 是对手，不要弄混。
- verdict 的含义：same 和引擎一致，ok 可以接受，mild 引擎不太喜欢，bad 引擎不认同，guess 引擎的首选是猜测的招式（玩家未必有），在确定有的招式里玩家选的就是最好的——不算失误。
- guessed_moves 是没贴队伍时引擎猜测的招式，玩家未必有，不要据此批评。
- 胜率的大起大落可能来自运气（会心一击、没命中、麻痹等，见 log）或对手没走引擎预想的应对（opponent_expected 与 opponent_did）：不要把它们算成玩家的失误，
  也不要算成玩家的功劳。swings 是程序算好的胜率变化最大的几处（change 正为上升、负为下降），带着玩家那一步的损失 your_loss、
  对手实际的选择和引擎最预计的应对各自对应的玩家胜率、那几回合 log 里的运气（luck_in_log：会心一击、没命中、不能动；ME 是玩家，OPP 是对手，看清是谁的运气）。
  讲到胜率大幅上升或下降（相邻决策的 position_win_chance 变化 15 个百分点以上，swings 里都有）时，先找原因：
  看那一步 opponent_did 在 opponent_expected 里对应的 your_win_chance，和引擎最预计的应对比，差得多就是对手的选择带来的（对手失误或妙手）；
  opponent_did_unexpected 为 true 时引擎没料到这一手、没有对应的数字，就看下一个决策的 position_win_chance 变了多少；
  log 里有会心一击、没命中等就是运气；都不是才是玩家自己打出来的。逆转或翻车要如实说清是谁、哪一回合造成的。
- 解释“为什么”时，用数据包里的事实：属性相克（takes）、速度（种族值 base.spe）、道具、特性、能力变化、场地。
- 每个结论都要引用具体回合，例如“第 35 回合”。""",
    "en": """Rules:
- "The engine" is this app's own battle AI (a neural network with search): the data's chances
  and verdicts are its. You are the coach; call it "the engine".
- This game's facts (moves, items, abilities, sets, what happened, the numbers) come only from
  the data. Do not invent moves, items, abilities, sets or events; say you don't know what the
  data does not show.
- The engine's analysis is a model's and not perfect: its chances, verdicts, expected replies
  and lines (ai_lines) come from a neural network and a few seconds of search. It looks a few
  turns ahead, so long-term matters (keeping a win condition, the slow value of hazards and
  chip damage, how an endgame closes) can escape it; the opponent's unrevealed sets are its
  guesses; its chances have errors. Take the engine as the main reference, and judge as a coach
  too, with general knowledge of Pokémon battles (types and matchups, common plans, win
  conditions, tempo). Where you think the engine missed something or you see it differently,
  say so -- as your view, with the reason, kept apart from the engine's numbers; do not
  disagree for its own sake. Remind the reader once, where it fits, that the engine is not
  perfect; not in every paragraph.
- Name Pokémon, moves, items, abilities and types in English exactly as the data does.
- The engine's numbers are estimates from a few seconds of search: say "the engine thought ... was better
  (about X% vs Y% to win)" -- X the ai_choice_win_chance, Y the chosen_win_chance (the
  position_win_chance is the position's before the move, no option's) -- never that a move was
  certainly wrong. A gap under 3 points is no mistake; take the mistakes by loss, largest first.
- A terastallized Pokémon takes hits by its tera type alone (from the turn of its -terastallize
  in the log), not its old types.
- For a "switch after a faint", which one fainted is the log's faint line of that turn (ME the
  player, OPP the opponent): do not mix them up.
- verdict: same = the engine's own choice, ok = acceptable, mild = the engine doesn't like it, bad = the
  engine disagrees, guess = the engine's first choice is a move it only guessed the player has; among the
  moves the player surely has, the choice was the best -- no mistake.
- guessed_moves are the engine's guesses of the player's moves (no team pasted): the player may not
  have them; do not criticize on them.
- Big swings can come from luck (critical hits, misses, full paralysis: see the log) or from the
  opponent not playing what the engine expected (opponent_expected vs opponent_did): count them
  neither as the player's mistakes nor as the player's credit. swings lists the largest moves
  (change > 0 up, < 0 down) with the player's loss there (your_loss), the player's chance after
  the opponent's actual reply and after the engine's most expected one, and the luck in those turns'
  log (luck_in_log: crits, misses, full paralysis -- ME the player, OPP the opponent: whose luck).
  When the chance rises or falls a lot (position_win_chance moving 15 points or more between
  decisions, all in swings), find the cause first:
  the your_win_chance of opponent_did in opponent_expected against the engine's most expected reply
  -- far apart: the opponent's choice did it (a mistake or a good play; opponent_did_unexpected:
  a reply the engine did not weigh, no number -- see how the next decision's position_win_chance
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
玩家每个决策时一个引擎（这个程序自己的对战 AI：神经网络 + 搜索）的看法（各选项的胜率估计 win_chance 和思考比例 share、引擎的选择 ai_choice、
损失 loss、判定 verdict、引擎预计的对手应对和对手实际的选择、引擎预想的走向 ai_lines），以及中英文名对照 names_zh。
opponent_archetype 是从对手亮出的部分猜的对手流派（style 风格、features 特色、about 打法和一般的克制方法），只是猜测，讲到时说“看起来像”。
{rules}
用简体中文写，亲切、具体、通俗（玩家可能是孩子也可能是老手：说法要让谁都听得懂），不超过 900 字。分五节：
1. 总体风格（2-3 句：这局是怎么打的，偏进攻还是稳健，换人多不多，太晶用在哪）
2. 这局的转折点（1-3 个胜率变化最大的地方，按变化大小排：哪一回合、胜率从多少到多少、原因是玩家的选择、对手的失误或妙手、还是运气；
   双方最大的失误都要在这里，赢了也要说清有没有靠对手送或运气）
3. 做得好的地方（2-3 点，每点有回合和数字；只算玩家自己打出来的）
4. 可以改进的习惯（2-4 点：一个反复出现的模式，哪几个回合，引擎当时更想怎么做以及为什么）
5. 下次可以练习（2-3 条具体建议）""",
        "en": """You are a Pokémon Showdown Gen 9 OU coach, telling a passionate Pokémon fan about their playing style in
one game. You get the game's data as JSON: both teams (you = the player, opponent), the
turn-by-turn log (ME = the player, OPP = the opponent), and for each of the player's decisions
the engine's view -- this app's own battle AI, a neural network with search -- (each option's estimated win_chance and its share of the engine's thinking,
the engine's choice ai_choice, the loss, the verdict, the opponent's reply the engine expected and what
the opponent did, the engine's expected lines ai_lines). opponent_archetype is the opponent's
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
4. Habits to work on (2-4 points: a pattern that came up more than once, the turns, what the engine
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
- team_facts.this_game 是这一局双方阵容的对位拆解：first_turn 是引擎在第一回合估计的玩家胜率和当时的看法；
  their_pokemon_vs_your_team 是对手每只宝可梦在你队里被谁挡住或先手打倒（answered_by，check 能硬接、revenge 能先手打倒）、能一击打倒你哪几只（kos_in_one_hit）；
  your_pokemon_vs_their_team 反过来是你的每只被对手的谁挡住、能一击打倒对手哪几只；speed_order 是双方速度排序；
  species_model 是对局模型只看这 12 只宝可梦的胜率（ratings 相同时），拆成整体强度 strength、两两克制 matchups、队友配合 teammates 三部分的胜率点数，
  pairs_against_you / pairs_for_you 是最吃亏、最占便宜的几对；archetypes 是双方流派和这两种风格对战的历史记录。
  配置是按这局亮出来的部分加常见配置推测的（your_sets_exact 为 false 时你的也是），伤害是估算：说“大概”“估算”。
- 第一回合胜率明显低于或高于 50% 时，要用 this_game 讲清楚原因：是谁克制了谁、哪几只没人挡得住、速度谁占优、哪部分拉低了胜率；
  弱点和优化方向要从这一局的拆解出发，再用环境数据（team_facts.metagame）判断这是这局对手特有的问题，还是在整个环境里都常见。
用简体中文写，亲切、具体、通俗（玩家可能是孩子也可能是老手：说法要让谁都听得懂），不超过 1000 字。分五节：
1. 队伍构成（每只大概担任什么角色，流派）
2. 这一局的对阵拆解（开局胜率为什么是这个数：对手哪几只你挡不住、你的哪几只被谁挡住、速度和流派上谁占优；用 this_game 的数据和回合）
3. 优点（2-3 点）
4. 由此看出的弱点（从这局的拆解出发：这局暴露的问题，再看环境里是否常见——常见的才是真正要补的弱点）
5. 优化方向（2-4 条，具体：针对上面的弱点，换配置、换成员或换打法，各说取舍）""",
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
- team_facts.this_game breaks down this game's two teams against each other: first_turn the engine's
  chance for the player on the first turn and its view then; their_pokemon_vs_your_team each
  opponent's Pokemon with who of the player's team checks it or revenge-kills it (answered_by) and
  whom it KOs in one hit (kos_in_one_hit); your_pokemon_vs_their_team the same the other way;
  speed_order both teams by speed; species_model the matchup model's chance from these twelve
  species alone (even ratings), split into points of strength, matchups and teammates, with the
  pairs most against and for the player; archetypes both styles and that pairing's record. The
  sets are what the game showed plus the usual sets (the player's too when your_sets_exact is
  false) and the damage an estimate: say "about", "estimated".
- When the first turn's chance is clearly off 50%, explain why from this_game: who counters whom,
  which ones nobody answers, who is faster, which part pulled the chance down. Derive the
  weaknesses and the directions from this game's breakdown, then use the metagame data
  (team_facts.metagame) to tell a problem of this opponent from one common in the metagame.
Write in English, friendly and concrete, plain enough for any player (a child or a veteran), under 700 words. Five sections:
1. The team (each member's rough role, its archetype)
2. This game's matchup (why the first turn's chance is what it is: which of theirs the team cannot
   answer, which of the player's they wall, speed and style -- with this_game's data and turns)
3. Strengths (2-3)
4. The weaknesses this shows (from the breakdown: what this game exposed, then whether the
   metagame makes it common -- the common ones are the weaknesses worth fixing)
5. Directions (2-4, concrete: for those weaknesses, a set change, a member change or a way of
   playing, each with its trade-off)""",
}

SYSTEMS["turn"] = {
    "zh": """你是宝可梦 Showdown 第九世代 OU 的教练，在给一位热血的宝可梦爱好者讲这局里的某一步（数据里的 you / 玩家就是这位爱好者）。
你会收到 JSON 数据包：双方队伍、这一回合和前两回合的日志、这一步的数据 decision（玩家的选择 chosen、
各选项的胜率估计和引擎思考比例、引擎的选择、判定、当时的场面 state、引擎预计的对手应对 opponent_expected
和对手实际的选择 opponent_did、引擎预想的走向 ai_lines），以及中英文名对照 names_zh。
{rules}
用简体中文写，亲切、具体，不超过 350 字。如果有玩家的提问，就直接回答这个问题；没有的话，讲清楚：
当时的局面、玩家的选择和引擎的看法、引擎为什么这样看（对手可能怎么应对、接下来会怎样）、这一步可以学到什么。""",
    "en": """You are a Pokémon Showdown Gen 9 OU coach explaining one decision of a game to a passionate Pokémon fan.
You get JSON: both teams, the log of this turn and the two before, the decision (the player's
choice chosen, each option's estimated win_chance and the engine's share of thinking, the engine's
choice, the verdict, the public state, the opponent's replies the engine expected and what it did,
the engine's expected lines ai_lines).
{rules}
Write in English, friendly and concrete, under 200 words. If the player asks a question, answer
it; otherwise explain the position, the player's choice and the engine's view, why the engine sees it so
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


def is_local(base_url: str) -> bool:
    """A model served on this computer (Ollama: http://localhost:11434/v1): no key needed."""
    try:
        host = urlsplit(base_url.strip()).hostname or ""
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1")


def ready(settings: dict) -> bool:
    """An address, a model, and a key unless the model is served on this computer."""
    return bool(settings["base_url"] and settings["model"]
                and (settings["api_key"] or is_local(settings["base_url"])))  # fmt: skip


def public_settings(coach: Path) -> dict:
    """What a page may see: the URL, the model, whether a key is set -- never the key --, whether
    the coach is ready (``ready``; a local model needs no key: ``local``), the persona and the
    personas to choose from ([id, English name, Chinese name, English title, Chinese title];
    "none": no role)."""
    s = load_settings(coach)
    return {"base_url": s["base_url"], "model": s["model"], "has_key": bool(s["api_key"]),
            "ready": ready(s), "local": is_local(s["base_url"]),
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


def key_for(coach: Path, base_url: str, api_key: str) -> str:
    """The key to call ``base_url`` with: the one given, else the saved one -- for the saved
    address only (a saved key never goes to an address typed since)."""
    if api_key.strip():
        return api_key.strip()
    s = load_settings(coach)
    same = base_url.strip().rstrip("/") == s["base_url"].rstrip("/")
    return s["api_key"] if same else ""


def list_models(base_url: str, api_key: str, timeout: float = 20) -> list[str]:
    """The models the service offers, sorted: OpenAI's GET /models ({"data": [{"id"}]}), which
    Ollama, OpenRouter, DeepSeek and the like serve too (a list under "models" taken as well)."""
    if not base_url.strip():
        raise RuntimeError("no address")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.strip().rstrip("/") + "/models"
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
    except requests.Timeout:
        raise RuntimeError(f"no answer from {url} in {timeout:.0f} s") from None
    except requests.RequestException:
        raise RuntimeError(
            f"cannot reach {url} -- is the address right, the service running?"
        ) from None
    if r.status_code != 200:
        raise RuntimeError(f"the model's service answered {r.status_code}: {r.text[:300]}")
    body = r.json()
    items = (body.get("data") or body.get("models") or []) if isinstance(body, dict) else body
    ids = {
        str((m.get("id") or m.get("name") or "") if isinstance(m, dict) else m) for m in items or []
    }
    return sorted(ids - {""})


def chat(
    settings: dict, system: str, user: str, timeout: float = 300, messages: list | None = None
) -> str:
    """One answer of the configured chat model (OpenAI's /chat/completions); ``messages``: a
    conversation after the system prompt (user / assistant turns) instead of ``user`` alone."""
    if not ready(settings):
        raise RuntimeError("no_llm")
    headers = {"Content-Type": "application/json"}
    if settings["api_key"]:  # (a local model: none)
        headers["Authorization"] = f"Bearer {settings['api_key']}"
    r = requests.post(
        settings["base_url"].rstrip("/") + "/chat/completions",
        headers=headers,
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
DEFAULT_QUESTION = {
    "zh": "引擎为什么这样看这一步？",
    "en": "Why does the engine see this decision so?",
}
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
