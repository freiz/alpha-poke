"""A game review as one HTML page (2026-10-29): Showdown's own replay player (sprites,
animations: its replay-embed.js, MIT, loaded from play.pokemonshowdown.com -- the client's look
and data stay current without us) next to the review: the winning-chance curve with the
mistakes marked, each decision's options (the search's winning chance and share of visits), the
player's choice and the search's; previous / next decision, next mistake, the keyboard; the
player and the panel follow each other (Battle.seekTurn / subscribe). Open it in a browser (a
local file: it needs the internet for the player's scripts and sprites)."""

import json

from alpha_poke.coach.review import mistake_score, turn_events

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Game review</title>
<style>
  :root { --bg: #f5f6f8; --panel: #ffffff; --ink: #1d2330; --muted: #677085; --line: #d9dde5;
          --good: #2f9e5b; --bad: #d64545; --mild: #c9a227; --ai: #3567d6; --me: #e08a1e; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #15181e; --panel: #1f242d; --ink: #e6e9ef; --muted: #9aa3b5; --line: #343b48; }
  }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 14px/1.45 system-ui, sans-serif; }
  header { padding: 10px 16px; display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }
  header h1 { font-size: 18px; margin: 0; }
  header .res { font-weight: 600; }
  main { display: flex; gap: 16px; padding: 0 16px 16px; align-items: flex-start; flex-wrap: wrap; }
  .wrapper.replay-wrapper { flex: 0 0 auto; width: 640px; max-width: 100%; position: relative; }
  .wrapper .battle-log { height: 160px !important; position: static !important; width: auto !important; }
  #panel { flex: 1 1 420px; min-width: 320px; background: var(--panel); border: 1px solid var(--line);
           border-radius: 10px; padding: 12px 14px; }
  #curve { width: 100%; height: 150px; display: block; cursor: pointer; }
  .nav { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0 10px; }
  .nav button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 6px;
                padding: 5px 10px; cursor: pointer; font: inherit; }
  .nav button:hover { border-color: var(--ai); }
  .dec { border-top: 1px solid var(--line); padding: 10px 0 4px; }
  .dec h3 { margin: 0 0 6px; font-size: 15px; }
  .tag { display: inline-block; font-size: 12px; padding: 1px 7px; border-radius: 10px; margin-left: 6px; }
  .tag.bad { background: var(--bad); color: #fff; } .tag.ok { background: var(--good); color: #fff; } .tag.mild { background: var(--mild); color: #fff; }
  .tune { font-size: 12px; color: var(--muted); display: flex; gap: 14px; flex-wrap: wrap; align-items: center; margin: 4px 0 2px; }
  .tune input { vertical-align: middle; width: 110px; } .tune b { color: var(--ink); }
  .opt { display: grid; grid-template-columns: minmax(96px, 150px) 1.4fr 76px 1fr 40px; gap: 6px 8px; align-items: center; margin: 3px 0; }
  .opt.head { color: var(--muted); font-size: 12px; margin-top: 6px; } .opt.head span:nth-child(2) { grid-column: 2 / 4; } .opt.head span:nth-child(3) { grid-column: 4 / 6; }
  .opt .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .opt .name.me { color: var(--me); font-weight: 600; } .opt .name.ai { color: var(--ai); font-weight: 600; }
  .bar { position: relative; height: 14px; background: var(--bg); border-radius: 3px; overflow: hidden; }
  .aibox .bar { background: var(--panel); }
  .bar span { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px; }
  .bar .win { background: var(--ai); opacity: .8; } .bar .share { background: var(--muted); opacity: .7; }
  .diff { color: var(--muted); font-size: 11px; }
  .home { font-size: 13px; color: var(--ai); text-decoration: none; margin-right: 4px; } .home:hover { text-decoration: underline; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .legend, .state, .events { color: var(--muted); font-size: 12px; }
  .events { white-space: pre-wrap; margin-top: 6px; max-height: 120px; overflow: auto; }
  .moments li { cursor: pointer; margin: 2px 0; } .moments li:hover { color: var(--ai); }
  .none { color: var(--muted); padding: 10px 0; }
  #turnhead { margin: 6px 0 4px; font-size: 16px; }
  .step { border-left: 3px solid var(--line); padding: 6px 0 6px 10px; margin: 6px 0; }
  .step.me { border-left-color: var(--me); } .step.opp { border-left-color: var(--muted); }
  .step.sel { background: color-mix(in srgb, var(--ai) 10%, transparent); }
  .stitle { font-size: 12px; color: var(--muted); font-weight: 600; } .shead { font-weight: 600; margin: 2px 0; }
  .slines { color: var(--muted); font-size: 12px; } .aibox { margin-top: 8px; padding: 8px; background: var(--bg); border-radius: 6px; }
  .aihead { font-weight: 600; margin-bottom: 4px; }
  .score { display: flex; gap: 12px; flex-wrap: wrap; padding: 0 16px 12px; align-items: stretch; }
  .tile { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 8px 16px; min-width: 130px; }
  .tile b { display: block; font-size: 28px; line-height: 1.2; font-variant-numeric: tabular-nums; }
  .tile b small { font-size: 13px; color: var(--muted); font-weight: 400; margin-left: 4px; }
  .tile span { color: var(--muted); font-size: 12px; } .score .legend { align-self: flex-end; max-width: 360px; }
  .lang { margin-left: auto; font-size: 12px; color: var(--muted); }
  .lang button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); padding: 2px 8px; cursor: pointer; font: inherit; }
  .lang button.sel { background: var(--ai); color: #fff; border-color: var(--ai); }
</style>
<header>
  <a class="home" id="home" href="/" hidden></a><h1 id="title"></h1><span class="res" id="res"></span><span class="legend" id="note"></span>
  <span class="lang"><span id="lui"></span> <button data-k="ui" data-v="en">EN</button><button data-k="ui" data-v="zh">中文</button>
    &nbsp; <span id="lnames"></span> <button data-k="names" data-v="en">EN</button><button data-k="names" data-v="zh">中文</button></span>
</header>
<div class="score" id="score"></div>
<main>
  <div class="wrapper replay-wrapper">
    <div class="battle"></div><div class="battle-log"></div>
    <div class="replay-controls"></div><div class="replay-controls-2"></div>
  </div>
  <section id="panel">
    <svg id="curve"></svg>
    <div class="legend" id="curvenote"></div>
    <div class="tune"><span id="tunehead"></span>
      <label><span id="tz"></span> <input type="range" id="z" min="1" max="3" step="0.5" /> <b id="zv"></b></label>
      <label><span id="tl"></span> <input type="range" id="low" min="5" max="30" step="5" /> <b id="lowv"></b></label></div>
    <div class="nav">
      <button data-go="first"></button><button data-go="prev"></button>
      <button data-go="next"></button><button data-go="mistake"></button>
    </div>
    <h3 id="turnhead"></h3>
    <div id="decisions"></div>
    <h3 id="momentshead"></h3><ol class="moments" id="moments"></ol>
  </section>
</main>
<script type="text/plain" class="battle-log-data">__LOG__</script>
<script>
const R = __REVIEW__;
const SIDE = R.side;
let cur = 0;  // index into R.decisions
// the two languages: the panel's (ui) and the names' (Pokemon, moves, items, abilities; also
// Showdown's battle text) -- English by default; ?ui=zh&names=zh or the buttons (remembered)
const Q = new URLSearchParams(location.search);
function pref(k) {
  let v = Q.get(k);
  if (!v) { try { v = localStorage.getItem("coach-" + k); } catch (e) {} }
  return v == "zh" ? "zh" : "en";
}
const UI = pref("ui"), NAMES = pref("names");
function setPref(k, v) {
  try { localStorage.setItem("coach-" + k, v); } catch (e) {}
  const u = new URL(location.href); u.searchParams.set(k, v); location.href = u.toString();
}
const STATS = {
  en: {atk: "Attack", def: "Defense", spa: "Sp. Atk", spd: "Sp. Def", spe: "Speed", accuracy: "accuracy", evasion: "evasion",
       attack: "Atk", defense: "Def", special_attack: "SpA", special_defense: "SpD", speed: "Spe",
       stealth_rock: "Stealth Rock", spikes: "Spikes", toxic_spikes: "Toxic Spikes", sticky_web: "Sticky Web",
       brn: "burned", par: "paralyzed", slp: "asleep", frz: "frozen", psn: "poisoned", tox: "badly poisoned",
       RainDance: "rain", SunnyDay: "harsh sunlight", Sandstorm: "a sandstorm", Snowscape: "snow", Snow: "snow", none: "none"},
  zh: {atk: "攻击", def: "防御", spa: "特攻", spd: "特防", spe: "速度", accuracy: "命中率", evasion: "闪避率",
       attack: "攻击", defense: "防御", special_attack: "特攻", special_defense: "特防", speed: "速度",
       stealth_rock: "隐形岩", spikes: "撒菱", toxic_spikes: "毒菱", sticky_web: "黏黏网",
       brn: "灼伤", par: "麻痹", slp: "睡眠", frz: "冰冻", psn: "中毒", tox: "剧毒",
       RainDance: "下雨", SunnyDay: "大晴天", Sandstorm: "沙暴", Snowscape: "下雪", Snow: "下雪", none: "无"},
};
const T = {
  en: {
    title: id => `Review · ${id}`, won: "won", lost: "lost",
    note: (ms, w) => `Your side: ${SIDE == "p1" ? "p1 (bottom left)" : "p2"} | winning chances are the AI search's estimates (${ms} ms × ${w} belief worlds per decision)`,
    ui: "Interface", names: "Names",
    curve: "Your winning chance through the game, by turn (● your choice at the start of a turn, ○ your switch after a faint or a pivot move; red: the AI clearly disagreed). Click to jump; ←/→ previous / next turn, M next mistake.",
    first: "⏮ Start", prev: "◀ Previous turn", next: "Next turn ▶", mistake: "⚠ Next mistake",
    momentsHead: "Where the AI disagreed most", noMoments: "No clear mistakes.",
    turn: t => `Turn ${t}`, chanceStart: v => `your winning chance at its start: ${v}`,
    lead: "Leads", end: "End of the turn", before: "Before the actions",
    you: "You", opp: "Opponent",
    kinds: {move: "move", cant: "could not move", switch: "switch", pivot: "switch (pivot move)", replace: "switch after a faint", drag: "forced out", choice: "your choice"},
    aiHead: {turn: "The AI on your choice at the start of the turn", "pivot switch": "The AI on your switch", "switch after a faint": "The AI on your switch"},
    chanceAt: v => `your winning chance at this decision: ${v}`, bad: "AI disagrees", mild: "AI doesn't like it", same: "same as the AI", ok: "acceptable",
    bars: `<span style="color:var(--me)">Orange</span> = your choice, <span style="color:var(--ai)">blue</span> = the AI's choice. In brackets: the difference from the AI's choice.`,
    winCol: "Winning chance after it", shareCol: "The AI's share of thinking", home: "← Home",
    tune: "How strict:", tz: "a gap counts beyond", tzv: v => `${v}× its error`, tl: "the AI shuns a choice it thinks about less than", tlv: v => `${v}%`,
    noteRuns: n => n > 1 ? ` × ${n} searches` : "", approx: "≈",
    noteTeam: t => t ? " | your team: pasted (exact)" : " | your team: what the game showed, the rest guessed",
    visits: n => `${n.toLocaleString("en")} visits`,
    top1: "Matched the AI's first choice", top2: "In the AI's top two", meanLoss: "Average winning chance lost", pts: "pts",
    badMild: "AI disagreed / didn't like it",
    scoreNote: n => `Over your ${n} decisions with a choice; the last tile follows the strictness below.`,
    untried: "untried", left: n => `${n} left`, tera: "terastallized",
    hazMe: "hazards on your side", hazOpp: "on the opponent's side", unseen: x => `You chose ${x} (the log does not show it as such)`,
    switchTo: x => `Switch to ${x}`, teraSuffix: " + Tera",
    moment: (t, c, b, cv, bv) => `Turn ${t}: you chose <b>${c}</b>, the AI <b>${b}</b> (${cv} → ${bv})`,
    mine: x => `your ${x}`, theirs: x => `the opposing ${x}`, side: me => me ? "your side" : "the opposing side",
    ev: {
      move: (a, m, t) => `${cap(a)} used ${m}` + (t && t != a ? ` on ${t}` : ""), switch: (a, hp) => `${cap(a)} came in (${hp})`,
      drag: a => `${cap(a)} was dragged in`, replace: a => `${cap(a)} was revealed`, faint: a => `${cap(a)} fainted`,
      "-supereffective": a => `super effective on ${a}`, "-resisted": a => `${cap(a)} resisted it`, "-crit": () => "a critical hit",
      "-immune": (a, f) => `${cap(a)} is immune` + (f ? ` (${f})` : ""), "-miss": a => `${cap(a)} missed`, "-fail": a => `it failed`,
      "-block": (a, f) => `${cap(a)} blocked it` + (f ? ` (${f})` : ""), "-notarget": () => "no target",
      "-terastallize": (a, t) => `${cap(a)} terastallized into the ${t} type`, "-boost": (a, s, n) => `${cap(a)}'s ${s} rose by ${n}`,
      "-unboost": (a, s, n) => `${cap(a)}'s ${s} fell by ${n}`, "-setboost": (a, s, n) => `${cap(a)}'s ${s} set to ${n}`,
      "-clearallboost": () => "all stat changes were removed", "-clearboost": a => `${cap(a)}'s stat changes were removed`,
      "-clearnegativeboost": a => `${cap(a)}'s lowered stats were restored`,
      "-sidestart": (sd, c) => `${cap(sd)}: ${c} set`, "-sideend": (sd, c) => `${cap(sd)}: ${c} removed`,
      "-enditem": (a, i, f) => `${cap(a)} lost its ${i}` + (f ? ` (${f})` : ""), "-item": (a, i, f) => `${cap(a)} holds ${i}` + (f ? ` (${f})` : ""),
      "-ability": (a, ab) => `${cap(a)}'s ability: ${ab}`, "-endability": a => `${cap(a)}'s ability was suppressed`,
      "-status": (a, st, f) => `${cap(a)} is ${st}` + (f ? ` (${f})` : ""), "-curestatus": (a, st) => `${cap(a)} is no longer ${st}`,
      "-damage": (a, hp, f) => `${cap(a)}: ${hp} left` + (f ? ` (${f})` : ""), "-heal": (a, hp, f) => `${cap(a)} healed to ${hp}` + (f ? ` (${f})` : ""),
      "-sethp": (a, hp) => `${cap(a)}: ${hp}`, "-hitcount": (a, n) => `hit ${n} times`,
      "-weather": (w, up) => up ? `${cap(w)} continues` : `the weather: ${w}`, "-fieldstart": c => `${c} started`, "-fieldend": c => `${c} ended`,
      "-start": (a, c) => `${cap(a)}: ${c}`, "-end": (a, c) => `${cap(a)}: ${c} ended`, "-activate": (a, c) => `${cap(a)}: ${c}`,
      "-singleturn": (a, c) => `${cap(a)}: ${c}`, "-prepare": (a, m) => `${cap(a)} is preparing ${m}`, "-mustrecharge": a => `${cap(a)} must recharge`,
      "-transform": (a, b) => `${cap(a)} transformed into ${b}`, "-formechange": (a, f) => `${cap(a)} changed form: ${f}`, detailschange: (a, f) => `${cap(a)} became ${f}`,
      cant: (a, r) => `${cap(a)} could not move (${r})`, "-message": m => m, win: w => `Winner: ${w}`, tie: () => "A tie",
    },
  },
  zh: {
    title: id => `复盘 · ${id}`, won: "胜", lost: "负",
    note: (ms, w) => `分析视角：${SIDE == "p1" ? "p1（左下）" : "p2"} ｜ 胜率为 AI 搜索的估计（每步 ${ms} ms × ${w} 个信念世界）`,
    ui: "界面", names: "名称",
    curve: "整局的胜率变化，按回合（● 回合开始时你的选择，○ 倒下后或折返后的换人；红色：AI 明显不认同）。点击跳转；←/→ 上一回合 / 下一回合，M 下一个失误。",
    first: "⏮ 开局", prev: "◀ 上一回合", next: "下一回合 ▶", mistake: "⚠ 下一个失误",
    momentsHead: "AI 最不认同的决策", noMoments: "没有明显的失误。",
    turn: t => `回合 ${t}`, chanceStart: v => `回合开始时你的胜率 ${v}`,
    lead: "开局：双方首发", end: "回合末", before: "行动之前",
    you: "你", opp: "对手",
    kinds: {move: "出招", cant: "无法行动", switch: "换人", pivot: "折返换人", replace: "倒下后换人", drag: "被强制换下", choice: "你的选择"},
    aiHead: {turn: "AI 怎么看你回合开始时的选择", "pivot switch": "AI 怎么看你这次换人", "switch after a faint": "AI 怎么看你这次换人"},
    chanceAt: v => `做这个决策时你的胜率 ${v}`, bad: "AI 不认同", mild: "AI 不太喜欢", same: "和 AI 一致", ok: "可以接受",
    bars: `<span style="color:var(--me)">橙色</span>=你的选择，<span style="color:var(--ai)">蓝色</span>=AI 的选择；括号里是和 AI 选择的胜率差距。`,
    winCol: "选这一步后的胜率", shareCol: "AI 思考的比例", home: "← 主页",
    tune: "判定标准：", tz: "胜率差距超出误差的", tzv: v => `${v} 倍才算数`, tl: "AI 思考比例低于", tlv: v => `${v}% 算不认同`,
    noteRuns: n => n > 1 ? ` × ${n} 次搜索` : "", approx: "≈",
    noteTeam: t => t ? " ｜ 我方队伍：已粘贴（精确）" : " ｜ 我方队伍：这局亮出来的部分，其余靠猜",
    visits: n => `访问 ${n.toLocaleString("en")} 次`,
    top1: "AI 一选吻合率", top2: "AI 前二吻合率", meanLoss: "平均每步胜率损失", pts: "点",
    badMild: "AI 不认同 / 不太喜欢",
    scoreNote: n => `只算有选择余地的 ${n} 步决策；最后一项随下面的判定标准变化。`,
    untried: "未尝试", left: n => `剩 ${n} 只`, tera: "已太晶",
    hazMe: "你这边的钉子", hazOpp: "对手那边的钉子", unseen: x => `你选择了 ${x}（日志里没有按这样显示）`,
    switchTo: x => `换上 ${x}`, teraSuffix: " + 太晶",
    moment: (t, c, b, cv, bv) => `回合 ${t}：你选了 <b>${c}</b>，AI 选 <b>${b}</b>（${cv} → ${bv}）`,
    mine: x => `你的 ${x}`, theirs: x => `对手的 ${x}`, side: me => me ? "你这一侧" : "对手那一侧",
    ev: {
      move: (a, m, t) => `${a} 使用了 ${m}` + (t && t != a ? `（对 ${t}）` : ""), switch: (a, hp) => `${a} 上场（${hp}）`,
      drag: a => `${a} 被强制拉上场`, replace: a => `${a} 的真身暴露了`, faint: a => `${a} 倒下了`,
      "-supereffective": a => `对 ${a} 效果绝佳`, "-resisted": a => `${a} 抵抗了（效果不好）`, "-crit": () => "击中要害（暴击）",
      "-immune": (a, f) => `${a} 免疫` + (f ? `（${f}）` : ""), "-miss": a => `${a} 的招式没有命中`, "-fail": () => "但是失败了",
      "-block": (a, f) => `${a} 挡住了` + (f ? `（${f}）` : ""), "-notarget": () => "没有目标",
      "-terastallize": (a, t) => `${a} 太晶化为 ${t} 属性`, "-boost": (a, s, n) => `${a} 的${s}提升 ${n} 级`,
      "-unboost": (a, s, n) => `${a} 的${s}下降 ${n} 级`, "-setboost": (a, s, n) => `${a} 的${s}变为 ${n} 级`,
      "-clearallboost": () => "所有能力变化被清除", "-clearboost": a => `${a} 的能力变化被清除`, "-clearnegativeboost": a => `${a} 下降的能力复原了`,
      "-sidestart": (sd, c) => `${sd}被放了 ${c}`, "-sideend": (sd, c) => `${sd}的 ${c} 被清除`,
      "-enditem": (a, i, f) => `${a} 的 ${i} 没了` + (f ? `（${f}）` : ""), "-item": (a, i, f) => `${a} 的道具是 ${i}` + (f ? `（${f}）` : ""),
      "-ability": (a, ab) => `${a} 的特性：${ab}`, "-endability": a => `${a} 的特性被消除了`,
      "-status": (a, st, f) => `${a} 陷入${st}状态` + (f ? `（${f}）` : ""), "-curestatus": (a, st) => `${a} 的${st}状态解除了`,
      "-damage": (a, hp, f) => `${a} 剩余 ${hp}` + (f ? `（${f}）` : ""), "-heal": (a, hp, f) => `${a} 回复到 ${hp}` + (f ? `（${f}）` : ""),
      "-sethp": (a, hp) => `${a} 的 HP 变为 ${hp}`, "-hitcount": (a, n) => `共击中 ${n} 次`,
      "-weather": (w, up) => up ? `${w}还在继续` : `天气：${w}`, "-fieldstart": c => `${c} 开始了`, "-fieldend": c => `${c} 结束了`,
      "-start": (a, c) => `${a}：${c}`, "-end": (a, c) => `${a}：${c} 结束`, "-activate": (a, c) => `${a}：${c}`,
      "-singleturn": (a, c) => `${a}：${c}`, "-prepare": (a, m) => `${a} 正在准备 ${m}`, "-mustrecharge": a => `${a} 需要休息一回合`,
      "-transform": (a, b) => `${a} 变身成了 ${b}`, "-formechange": (a, f) => `${a} 变成了 ${f}`, detailschange: (a, f) => `${a} 变成了 ${f}`,
      cant: (a, r) => `${a} 无法行动（${r}）`, "-message": m => m, win: w => `胜者：${w}`, tie: () => "平局",
    },
  },
};
const L = T[UI], ST = STATS[UI];
const cap = x => x ? x[0].toUpperCase() + x.slice(1) : x;
const pct = v => v == null ? "—" : Math.round(100 * v) + "%";
const esc = x => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;");
// names: Showdown's data (English) and its Simplified Chinese text (data/text/zh-cn.js, loaded with
// the player when NAMES is zh)
const idOf = x => String(x || "").toLowerCase().replace(/[^a-z0-9]/g, "");
function named(table, dex, x) {
  const id = idOf(x);
  if (NAMES == "zh") { const t = window.BattleText && BattleText["zh-cn"] && BattleText["zh-cn"][table]; if (t && t[id] && t[id].name) return t[id].name; }
  const d = window[dex]; return (d && d[id] && d[id].name) || x;
}
const monName = x => named("Pokedex", "BattlePokedex", x), moveName = x => named("Moves", "BattleMovedex", x);
const itemName = x => named("Items", "BattleItems", x), abilityName = x => named("Abilities", "BattleAbilities", x);
function typeName(x) {
  if (NAMES != "zh") return x;
  const t = window.BattleText && BattleText["zh-cn"] && BattleText["zh-cn"].TypeNames; return (t && t[x]) || x;
}
function option(o) {
  if (o.startsWith("switch ")) return L.switchTo(monName(o.slice(7)));
  const tera = o.endsWith("-tera"), id = tera ? o.slice(0, -5) : o;
  return moveName(id) + (tera ? L.teraSuffix : "");
}
function who(x) {  // "ME Garchomp" / "OPP Ting-Lu" -> your / the opposing (translated name)
  if (!x) return x;
  if (x.startsWith("ME ")) return L.mine(monName(x.slice(3)));
  if (x.startsWith("OPP ")) return L.theirs(monName(x.slice(4)));
  return x;
}
function effect(s) {  // "move: Taunt" / "ability: Water Absorb" / "item: Leftovers" / "Substitute" / "psn" -> its name
  if (!s) return "";
  s = s.replace("[from] ", "");
  if (s.startsWith("ability: ")) return abilityName(s.slice(9));
  if (s.startsWith("move: ")) return moveName(s.slice(6));
  if (s.startsWith("item: ")) return itemName(s.slice(6));
  if (ST[s]) return ST[s];
  if (s.startsWith("[")) return "";
  const m = moveName(s); if (m != s) return m;
  const a = abilityName(s); if (a != s) return a;
  return itemName(s);
}
function hp(x) {  // "343/380" / "47/100 psn" / "0 fnt" -> "90%" / "47% (poisoned)" / "0%"
  const m = /^(\d+)(?:\/(\d+))?\s*([a-z]*)/.exec(x || ""); if (!m) return x || "";
  const v = m[2] ? Math.round(100 * m[1] / m[2]) : +m[1];
  return v + "%" + (m[3] && m[3] != "fnt" ? ` (${ST[m[3]] || m[3]})` : "");
}
const fromOf = f => (f.find(x => x && x.startsWith("[from]")) || "");
function event(line) {
  const f = line.split("|"), tag = f[0], E = L.ev;
  if (!E[tag]) return null;
  const fr = effect(fromOf(f.slice(2)));
  switch (tag) {
    case "move": return E.move(who(f[1]), moveName(f[2]), who(f[3]));
    case "switch": case "drag": case "replace": return E[tag](who(f[1]), hp(f[3]));
    case "-immune": case "-block": return E[tag](who(f[1]), fr || effect(f[2]));
    case "-terastallize": return E[tag](who(f[1]), typeName(f[2]));
    case "-boost": case "-unboost": case "-setboost": return E[tag](who(f[1]), ST[f[2]] || f[2], f[3]);
    case "-sidestart": case "-sideend": return E[tag](L.side(f[1].startsWith("ME")), effect(f[2]));
    case "-enditem": case "-item": return E[tag](who(f[1]), itemName(f[2]), fr);
    case "-ability": return E[tag](who(f[1]), abilityName(f[2]));
    case "-status": return E[tag](who(f[1]), ST[f[2]] || f[2], fr);
    case "-curestatus": return E[tag](who(f[1]), ST[f[2]] || f[2]);
    case "-damage": case "-heal": return E[tag](who(f[1]), hp(f[2]), fr);
    case "-sethp": return E[tag](who(f[1]), hp(f[2]));
    case "-hitcount": return E[tag](who(f[1]), f[2]);
    case "-weather": return f[1] == "none" ? null : E[tag](ST[f[1]] || f[1], f.includes("[upkeep]"));
    case "-fieldstart": case "-fieldend": return E[tag](effect(f[1]));
    case "-start": case "-end": case "-activate": case "-singleturn": return E[tag](who(f[1]), effect(f[2]));
    case "-prepare": return E[tag](who(f[1]), moveName(f[2]));
    case "-transform": return E[tag](who(f[1]), who(f[2]));
    case "-formechange": case "detailschange": return E[tag](who(f[1]), monName((f[2] || "").split(",")[0]));
    case "cant": return E[tag](who(f[1]), effect(f[2]) || f[2]);
    case "-message": case "win": return E[tag](f[1]);
    default: return E[tag](who(f[1]), who(f[2]));
  }
}
// a turn's record as steps, in the order things happened: the leads (turn 1), each action (a move
// with its tera, a switch, a Pokemon that could not move) with what followed it, the end of the
// turn (after the log's blank line), the switches after a faint (after "upkeep")
function steps(t) {
  const out = [];
  if (t == 1 && R.events[0]) out.push({kind: "lead", side: null, main: null, lines: R.events[0].filter(Boolean)});
  let cur = null, phase = "act", tera = null, acted = false;
  for (const line of R.events[t] || []) {
    const f = line.split("|"), tag = f[0];
    if (tag === "") { if (acted && phase == "act") { phase = "end"; cur = null; } continue; }
    if (tag == "upkeep") { phase = "after"; cur = null; continue; }
    const side = (f[1] || "").startsWith("ME") ? "me" : (f[1] || "").startsWith("OPP") ? "opp" : null;
    if (tag == "-terastallize") { tera = line; continue; }
    if (tag == "move" || tag == "cant") {
      cur = {kind: tag, side, main: line, tera: tera && tera.split("|")[1] == f[1] ? tera : null, lines: []};
      tera = null; acted = true; out.push(cur); continue;
    }
    if (tag == "switch" || tag == "drag") {
      const kind = tag == "drag" ? "drag" : phase == "after" ? "replace" : fromOf(f) ? "pivot" : "switch";
      cur = {kind, side, main: line, lines: []}; if (phase == "act") acted = true; out.push(cur); continue;
    }
    if (!cur) { cur = {kind: phase == "act" ? "before" : "end", side: null, main: null, lines: []}; out.push(cur); }
    cur.lines.push(line);
  }
  // each decision of the player at its step: the turn's choice at the player's action, a pivot's
  // switch at the pivot switch, the switches after a faint in order; one the log does not show as
  // such (a called move, ...) as its own step
  const pools = {turn: ["move", "switch", "cant"], "pivot switch": ["pivot"], "switch after a faint": ["replace"]};
  const used = new Set();
  R.decisions.forEach((d, i) => {
    if (d.turn != t) return;
    const s = out.find(s => s.side == "me" && pools[d.kind].includes(s.kind) && !used.has(s));
    if (s) { used.add(s); s.dec = i; }
    else out.push({kind: "choice", side: "me", main: null, lines: [], dec: i});
  });
  return out;
}
function setting(k, d) { try { const v = parseFloat(localStorage.getItem("coach-" + k)); return isNaN(v) ? d : v; } catch (e) { return d; } }
let Z = setting("z", 2), LOW = setting("low", 10);
// as coach.review.verdict: "same"; "bad" -- the AI hardly thought of the choice and the chance it
// loses is beyond the noise (Z standard errors; without errors 5 points), or the loss alone is
// beyond the noise and at least 5 points; "mild" -- hardly thought of, the loss within the noise
function verdict(d) {
  if (d.chosen == d.best) return "same";
  const real = d.loss != null && (d.loss_se ? d.loss > Z * d.loss_se : d.loss >= 0.05);
  const shunned = d.chosen_share < LOW / 100 && d.options[0][1] >= 0.5;
  if (shunned) return real ? "bad" : "mild";
  return real && d.loss >= 0.05 ? "bad" : "ok";
}
const pm = se => se ? ` ±${Math.max(1, Math.round(100 * se))}` : "";
function aiHTML(d) {
  const v = verdict(d), tag = {bad: L.bad, mild: L.mild, same: L.same, ok: L.ok}[v];
  let h = `<div class="aibox"><div class="aihead">${L.aiHead[d.kind] || L.aiHead.turn} <span class="tag ${v == "same" ? "ok" : v}">${tag}</span> <span class="legend">${L.chanceAt(pct(d.value) + pm(d.value_se))}${d.visits ? " · " + L.visits(d.visits) : ""}</span></div>`;
  h += `<div class="legend">${L.bars}</div>`;
  h += `<div class="opt head"><span></span><span>${L.winCol}</span><span>${L.shareCol}</span></div>`;
  const opts = d.options.slice();
  if (!opts.some(o => o[0] == d.chosen)) opts.push([d.chosen, d.chosen_share, d.chosen_value, null]);
  const bestSe = (d.options[0] || [])[3];
  for (const [o, share, q, se] of opts) {
    const cls = o == d.chosen ? "me" : o == d.best ? "ai" : "";
    let diff = "";
    if (q != null && o != d.best) {  // the gap to the AI's choice, "≈" within Z errors
      const gap = q - d.best_value, gse = se && bestSe ? Math.hypot(se, bestSe) : null;
      diff = ` <span class="diff">(${gse && Math.abs(gap) <= Z * gse ? L.approx : (gap >= 0 ? "+" : "") + Math.round(100 * gap)})</span>`;
    }
    h += `<div class="opt"><span class="name ${cls}" title="${esc(o)}">${esc(option(o))}</span>
      <span class="bar"><span class="win" style="width:${q == null ? 0 : 100 * q}%"></span></span>
      <span class="num">${q == null ? L.untried : pct(q) + pm(se)}${diff}</span>
      <span class="bar"><span class="share" style="width:${100 * share}%"></span></span>
      <span class="num">${pct(share)}</span></div>`;
  }
  const st = d.state, me = st.me, op = st.opp;
  const b = x => Object.entries(x || {}).map(([k, v]) => (ST[k] || k) + " " + (v > 0 ? "+" + v : v)).join(", ");
  const sideText = (s, label) => `${label}: ${esc(monName(s.active.species))} ${pct(s.active.hp)}${Object.keys(s.boosts || {}).length ? " (" + b(s.boosts) + ")" : ""} · ${L.left(s.alive)}${s.tera_used ? " · " + L.tera : ""}`;
  h += `<div class="state">${sideText(me, L.you)} | ${sideText(op, L.opp)}${Object.keys(me.hazards).length ? " | " + L.hazMe + ": " + b(me.hazards) : ""}${Object.keys(op.hazards).length ? " | " + L.hazOpp + ": " + b(op.hazards) : ""}</div>`;
  return h + "</div>";
}
function stepHTML(s, n) {
  const title = s.kind == "lead" ? L.lead : s.kind == "end" ? L.end : s.kind == "before" ? L.before
    : `${n}. ${s.side == "me" ? L.you : L.opp} · ${L.kinds[s.kind]}`;
  let head = s.kind == "choice" ? L.unseen(option(R.decisions[s.dec].chosen)) : [s.tera, s.main].filter(Boolean).map(event).filter(Boolean).join("; ");
  const lines = s.lines.map(event).filter(Boolean);
  let h = `<div class="step ${s.side || "neutral"}${s.dec != null && s.dec == selD ? " sel" : ""}" ${s.dec != null ? `data-dec="${s.dec}"` : ""}><div class="stitle">${esc(title)}</div>`;
  if (head) h += `<div class="shead">${esc(head)}</div>`;
  if (lines.length) h += `<div class="slines">${lines.map(x => "· " + esc(x)).join("<br>")}</div>`;
  if (s.dec != null) h += aiHTML(R.decisions[s.dec]);
  return h + "</div>";
}
function render() {
  const st = steps(curT);
  const start = R.decisions.find(d => d.turn == curT && d.kind == "turn");
  let n = 0;
  document.getElementById("turnhead").innerHTML = `${esc(L.turn(curT))}${start ? ` <span class="legend">${esc(L.chanceStart(pct(start.value)))}</span>` : ""}`;
  document.getElementById("decisions").innerHTML = st.map(s => stepHTML(s, ["lead", "end", "before"].includes(s.kind) ? 0 : ++n)).join("");
  // the decisions the AI disagreed with (under the current thresholds), most first
  const moments = R.decisions.map((d, i) => ({d, i})).filter(x => verdict(x.d) == "bad").sort((a, b) => b.d.score - a.d.score).slice(0, 5);
  document.getElementById("moments").innerHTML = moments.map(({d, i}) => `<li data-i="${i}">${L.moment(d.turn, esc(option(d.chosen)), esc(option(d.best)), d.chosen_value == null ? L.untried : pct(d.chosen_value), pct(d.best_value))}</li>`).join("") || `<li>${L.noMoments}</li>`;
  curve();
  scorecard();
  const sel = document.querySelector(".step.sel"); if (sel) sel.scrollIntoView({block: "nearest"});
}
// the game's scorecard (as coach.review.metrics): first / top-two choice matches and the mean loss
// over the decisions with a choice; the verdicts' counts under the current thresholds
function scorecard() {
  const ds = R.decisions.filter(d => d.options.length >= 2), n = ds.length;
  const rate = k => n ? Math.round(100 * ds.filter(d => d.options.slice(0, k).some(o => o[0] == d.chosen)).length / n) + "%" : "—";
  const cnt = k => `<small>${ds.filter(d => d.options.slice(0, k).some(o => o[0] == d.chosen)).length}/${n}</small>`;
  const losses = ds.filter(d => d.loss != null).map(d => Math.max(0, d.loss));
  const mean = losses.length ? (100 * losses.reduce((a, b) => a + b, 0) / losses.length).toFixed(1) : "—";
  const vs = R.decisions.map(verdict);
  const tile = (v, label) => `<div class="tile"><b>${v}</b><span>${label}</span></div>`;
  document.getElementById("score").innerHTML = tile(rate(1) + cnt(1), L.top1) + tile(rate(2) + cnt(2), L.top2)
    + tile(`${mean}<small>${L.pts}</small>`, L.meanLoss)
    + tile(`<span style="color:var(--bad);font-size:inherit">${vs.filter(v => v == "bad").length}</span> / <span style="color:var(--mild);font-size:inherit">${vs.filter(v => v == "mild").length}</span>`, L.badMild)
    + `<div class="legend">${esc(L.scoreNote(n))}</div>`;
}
// the curve by turn: a turn-start decision at its turn, a switch after a faint / a pivot halfway to
// the next; the current turn marked
function curve() {
  // drawn at the panel's own pixel width (a fixed viewBox stretched to it flattened the text)
  const s = document.getElementById("curve"), W = Math.max(200, s.clientWidth || 600), H = 150, P = 10, B = 14, last = Math.max(1, R.last_turn);
  s.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const x = t => P + (t - 1) * (W - 2 * P) / Math.max(1, last), y = v => P + (1 - v) * (H - P - B);
  const xd = d => x(d.turn + (d.kind == "turn" ? 0 : 0.5));
  let g = `<rect x="${x(curT) - 6}" y="${P - 4}" width="12" height="${H - B - P + 8}" fill="var(--line)" opacity=".6"/>`;
  for (const v of [0, .5, 1]) g += `<line x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-dasharray="${v == .5 ? "4 4" : "1 0"}"/><text x="${W - P - 2}" y="${y(v) - 3}" text-anchor="end" font-size="10" fill="var(--muted)">${100 * v}%</text>`;
  const every = Math.max(1, Math.ceil(last / 15));
  for (let t = 1; t <= last; t++) if (t == 1 || t % every == 0) g += `<text x="${x(t)}" y="${H - 2}" text-anchor="middle" font-size="10" fill="var(--muted)">${t}</text>`;
  g += `<polyline fill="none" stroke="var(--me)" stroke-width="2" points="${R.decisions.map(d => xd(d) + "," + y(d.value)).join(" ")}"/>`;
  R.decisions.forEach((d, i) => {
    const v = verdict(d), bad = v == "bad", mid = d.kind != "turn", color = bad ? "var(--bad)" : v == "mild" ? "var(--mild)" : "var(--me)";
    g += `<circle data-i="${i}" cx="${xd(d)}" cy="${y(d.value)}" r="${i == selD ? 6 : bad ? 5 : 4}" fill="${mid ? "var(--panel)" : color}" stroke="${i == selD ? "var(--ink)" : color}" stroke-width="2"><title>${esc(L.turn(d.turn))}${mid ? " · " + esc(L.kinds[d.kind == "pivot switch" ? "pivot" : "replace"]) : ""}: ${pct(d.value)}</title></circle>`;
  });
  s.innerHTML = g;
  s.dataset.last = last; s.dataset.w = W;
}
function battle() { return window.Replays && Replays.battle; }
let curT = 1, selD = null;
function go(t, dec = null, seek = true) {
  curT = Math.max(1, Math.min(Math.max(1, R.last_turn), t));
  selD = dec;
  render();
  const b = battle();
  if (seek && b) b.seekTurn(curT);
}
document.title = L.title(R.id);
document.documentElement.lang = UI == "zh" ? "zh" : "en";
document.getElementById("title").textContent = L.title(R.id);
if (location.protocol.startsWith("http")) { const a = document.getElementById("home"); a.textContent = L.home; a.hidden = false; }
document.getElementById("res").textContent = R.won ? L.won : L.lost;
document.getElementById("note").textContent = L.note(R.ms, R.worlds) + L.noteRuns(R.repeats || 1) + L.noteTeam(R.team);
document.getElementById("lui").textContent = L.ui;
document.getElementById("lnames").textContent = L.names;
document.getElementById("curvenote").textContent = L.curve;
document.getElementById("momentshead").textContent = L.momentsHead;
for (const k of ["first", "prev", "next", "mistake"]) document.querySelector(`[data-go="${k}"]`).textContent = L[k];
document.getElementById("tunehead").textContent = L.tune;
document.getElementById("tz").textContent = L.tz; document.getElementById("tl").textContent = L.tl;
for (const [id, get, set] of [["z", () => Z, v => { Z = v; }], ["low", () => LOW, v => { LOW = v; }]]) {
  const el = document.getElementById(id), out = document.getElementById(id + "v");
  const show = () => { out.textContent = id == "z" ? L.tzv(get()) : L.tlv(get()); };
  el.value = get(); show();
  el.addEventListener("input", () => { set(parseFloat(el.value)); show(); try { localStorage.setItem("coach-" + id, el.value); } catch (e) {} render(); });
}
document.querySelectorAll(".lang button").forEach(btn => {
  if ((btn.dataset.k == "ui" ? UI : NAMES) == btn.dataset.v) btn.classList.add("sel");
  btn.addEventListener("click", () => setPref(btn.dataset.k, btn.dataset.v));
});
function nextMistake() {
  const order = R.decisions.map((d, i) => i).filter(i => verdict(R.decisions[i]) == "bad");
  const after = order.find(i => R.decisions[i].turn > curT || (R.decisions[i].turn == curT && selD != null && i > selD));
  const i = after != null ? after : order[0];
  if (i != null) go(R.decisions[i].turn, i);
}
document.querySelector(".nav").addEventListener("click", e => {
  const a = e.target.dataset.go; if (!a) return;
  if (a == "first") go(1);
  if (a == "prev") go(curT - 1);
  if (a == "next") go(curT + 1);
  if (a == "mistake") nextMistake();
});
document.getElementById("curve").addEventListener("click", e => {
  const i = e.target.dataset && e.target.dataset.i;
  if (i != null) return go(R.decisions[+i].turn, +i);
  const s = e.currentTarget, r = s.getBoundingClientRect(), last = +s.dataset.last || 1, W = +s.dataset.w || r.width;
  const fx = (e.clientX - r.left) / r.width * W;
  go(Math.round(1 + (fx - 10) * Math.max(1, last) / (W - 20)));
});
document.addEventListener("keydown", e => {
  if (e.key == "ArrowLeft") go(curT - 1);
  if (e.key == "ArrowRight") go(curT + 1);
  if (e.key == "m" || e.key == "M") nextMistake();
});
document.getElementById("moments").addEventListener("click", e => { const li = e.target.closest("li"); if (li && li.dataset.i != null) go(R.decisions[+li.dataset.i].turn, +li.dataset.i); });
render();
window.addEventListener("resize", () => curve());
// the player in the names' language: Showdown's own translation (its Dex reads the language from
// its prefs; the zh-cn text data loaded before the battle is made)
function withNames(start) {
  if (NAMES != "zh" || !window.Dex) return start();
  const orig = Dex.prefs;
  Dex.prefs = function (p) { return p == "language" ? "zh-cn" : orig.call(Dex, p); };
  Dex.loadTextData("zh-cn").then(() => { chineseNicknames(); start(); }, start);
}
// Showdown shows a Pokemon by its nickname, which is its English name unless the player gave
// one: those (a nickname = its species or base species) become the Chinese name in the log the
// player reads; players' own nicknames stay
function chineseNicknames() {
  const el = document.querySelector("script.battle-log-data"), zh = BattleText["zh-cn"].Pokedex || {};
  const lines = el.textContent.split("\n"), rename = {};
  for (const line of lines) {
    const f = line.split("|");
    if ((f[1] == "switch" || f[1] == "drag" || f[1] == "replace") && f[2] && f[3]) {
      const ident = f[2].slice(0, 2), nick = f[2].split(": ").slice(1).join(": "), species = f[3].split(",")[0];
      const base = species.split("-")[0];
      for (const sp of [species, base]) {
        if (idOf(nick) == idOf(sp) && zh[idOf(sp)]) rename[ident + ":" + nick] = zh[idOf(sp)].name;
      }
    }
  }
  el.textContent = lines.map(line => line.replace(/(p[12])[a-c]?: ([^|]+)/g, (m, side, nick) => {
    const zhName = rename[side + ":" + nick.trim()];
    return zhName ? m.replace(nick, zhName) : m;
  })).join("\n");
}
// the player and the panel follow each other: hook the Battle's (single) subscription
const hook = setInterval(() => {
  const b = battle(); if (!b) return;
  clearInterval(hook);
  if (SIDE == "p2" && b.switchViewpoint) b.switchViewpoint();
  const prev = b.subscription;
  b.subscribe(function (state) {
    if (prev) prev.call(b, state);
    if ((state == "turn" || state == "paused" || state == "atqueueend") && b.turn >= 1 && b.turn != curT) {
      curT = Math.min(b.turn, Math.max(1, R.last_turn)); selD = null; render();
    }
  });
  render();  // (the names, now that the client's data has loaded)
  const m = /t=(\d+)/.exec(location.hash);  // #t=<turn>: open at that turn
  if (m) go(+m[1]);
}, 200);
</script>
__PLAYER__
</html>
"""

# official: Showdown's replay-embed.js from its site (works from a local file)
OFFICIAL = (
    '<script src="https://play.pokemonshowdown.com/js/replay-embed.js"></script>\n'
    "<script>document.addEventListener('DOMContentLoaded', function () {\n"
    "  var start = window.onload; window.onload = function () { withNames(function () { start && start(); }); };\n"
    "});</script>"
)

# local: the same client files from our server (coach.server: cached once, then offline), loaded
# in order; the player set up as replay-embed.js does (its Replays object, MIT, Guangcong Luo:
# adapted -- the play / pause / turn controls only)
LOCAL_FILES = ["js/lib/ps-polyfill.js", "config/config.js", "js/lib/jquery-1.11.0.min.js",
               "js/lib/html-sanitizer-minified.js", "js/battle-sound.js", "js/battledata.js",
               "data/pokedex-mini.js", "data/pokedex-mini-bw.js", "data/graphics.js",
               "data/pokedex.js", "data/moves.js", "data/abilities.js", "data/items.js",
               "data/teambuilder-tables.js", "js/battle-tooltips.js", "js/battle.js"]  # fmt: skip
LOCAL_STYLES = [
    "style/font-awesome.css",
    "style/battle.css",
    "style/replay.css",
    "style/utilichart.css",
]
LOCAL = (
    "<script>window.exports = window;</script>\n"
    + "".join(f'<link rel="stylesheet" href="/{f}" />\n' for f in LOCAL_STYLES)
    + "".join(f'<script src="/{f}"></script>\n' for f in LOCAL_FILES)
    + r"""<script>
var Replays = {
  battle: null,
  init: function () {
    var $el = $('.wrapper'), self = this;
    var log = ($('script.battle-log-data').text() || '').replace(/\\\//g, '/');
    this.battle = new Battle({id: '', $frame: $el.find('.battle'), $logFrame: $el.find('.battle-log'),
      log: log.split('\n'), isReplay: true, paused: true, autoresize: true});
    $el.on('click', '.replay-controls button', function (e) {
      var a = $(e.currentTarget).data('action');
      if (a === 'play') self.battle.play(); if (a === 'pause') self.battle.pause();
      if (a === 'reset') self.battle.reset(); if (a === 'rewind') self.battle.seekBy(-1);
      if (a === 'ff') self.battle.seekBy(1);
    });
    this.update();
    this.battle.subscribe(function () { self.update(); });
  },
  update: function () {
    var p = this.battle.paused, zh = typeof UI !== 'undefined' && UI === 'zh';
    var t = zh ? {play: '播放', pause: '暂停', reset: '重来', rewind: '上一回合', ff: '下一回合'}
               : {play: 'Play', pause: 'Pause', reset: 'Reset', rewind: 'Last turn', ff: 'Next turn'};
    $('.replay-controls').html('<button data-action="' + (p ? 'play' : 'pause') + '"><i class="fa fa-' + (p ? 'play' : 'pause') + '"></i> '
      + (p ? t.play : t.pause) + '</button><button data-action="reset"><i class="fa fa-undo"></i> ' + t.reset + '</button> '
      + '<button data-action="rewind"><i class="fa fa-step-backward"></i> ' + t.rewind + '</button><button data-action="ff">'
      + '<i class="fa fa-step-forward"></i> ' + t.ff + '</button>');
  }
};
window.addEventListener('load', function () { withNames(function () { Replays.init(); }); });
</script>"""
)


def render(report: dict, row: dict, client: str = "official") -> str:
    """The review page of ``report`` (coach.review) for the replay ``row``; ``client``: "official"
    (Showdown's site serves the player: open the file directly) or "local" (our server,
    coach.server: open http://127.0.0.1:<port>/coach/<review>/viewer.html)."""
    events = turn_events(row["log"], report["side"])  # (from the log: the current wording)
    ds = [{k: v for k, v in d.items() if k != "events"} | {"score": round(mistake_score(d), 3)}
          for d in report["decisions"]]  # fmt: skip
    # (the verdicts and the moments: computed by the page, its thresholds adjustable)
    won = report["winner"] == report["side"]
    data = {"id": report["id"], "side": report["side"], "won": won, "turns": report["turns"],
            "ms": report["settings"]["ms"], "worlds": report["settings"]["worlds"],
            "decisions": ds, "events": events, "repeats": report["settings"].get("repeats", 1),
            "team": report["settings"].get("team", False), "last_turn": max(events)}  # fmt: skip
    log = row["log"].replace("</", "<\\/")
    return (PAGE.replace("__REVIEW__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__LOG__", log)
            .replace("__PLAYER__", LOCAL if client == "local" else OFFICIAL))  # fmt: skip
