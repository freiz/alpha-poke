"""A game review as one HTML page (2026-10-29): Showdown's own replay player (sprites,
animations: its replay-embed.js, MIT, loaded from play.pokemonshowdown.com -- the client's look
and data stay current without us) next to the review: the winning-chance curve with the
mistakes marked, each decision's options (the search's winning chance and share of visits), the
player's choice and the search's; previous / next decision, next mistake, the keyboard; the
player and the panel follow each other (Battle.seekTurn / subscribe). Open it in a browser (a
local file: it needs the internet for the player's scripts and sprites)."""

import json

from alpha_poke.coach import form
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
  /* side by side and tall enough: the replay stays in view while the panel scrolls (2026-10-30: a
     long panel took it off the screen); stacked, it scrolls away as usual */
  @media (min-width: 1120px) and (min-height: 700px) {
    .wrapper.replay-wrapper { position: sticky; top: 8px; }
  }
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
  .opt { display: grid; grid-template-columns: minmax(96px, 150px) 1.4fr 38px 22px 42px 1fr 40px; gap: 6px 8px; align-items: center; margin: 3px 0; }
  .opt.head { color: var(--muted); font-size: 12px; margin-top: 6px; } .opt.head span:nth-child(2) { grid-column: 2 / 6; } .opt.head span:nth-child(3) { grid-column: 6 / 8; }
  .opt .se { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .opt .diff { white-space: nowrap; margin-left: -5px; }
  .opt .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .opt .name.me { color: var(--me); font-weight: 600; } .opt .name.ai { color: var(--ai); font-weight: 600; }
  .opt .name .guess { color: var(--muted); font-weight: 400; font-size: 12px; }
  .bar { position: relative; height: 14px; background: var(--bg); border-radius: 3px; overflow: hidden; }
  .aibox .bar { background: var(--panel); }
  .bar span { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px; }
  .bar .win { background: var(--ai); opacity: .8; } .bar .share { background: var(--muted); opacity: .7; }
  .diff { color: var(--muted); font-size: 11px; }
  .home { font-size: 13px; color: var(--ai); text-decoration: none; margin-right: 4px; } .home:hover { text-decoration: underline; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
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
  .aibox .opp { margin-top: 4px; } .jump { margin-top: 6px; padding: 6px 8px; border-left: 3px solid var(--ai); font-size: 13px; }
  .jump ul { margin: 4px 0 0 18px; padding: 0; }
  .llmbox { margin: 0 16px 12px; padding: 10px 14px; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; }
  .llmhead { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .llmhead button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; cursor: pointer; font: inherit; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  .llmwait { color: var(--muted); font-style: italic; padding: 8px 0; }
  .llmwait::before { content: ""; display: inline-block; width: 10px; height: 10px; margin-right: 8px; border: 2px solid var(--muted);
                     border-top-color: transparent; border-radius: 50%; animation: llmspin 1s linear infinite; vertical-align: -1px; }
  @keyframes llmspin { to { transform: rotate(360deg); } }
  .llmtext { font-size: 14px; line-height: 1.6; max-width: 980px; } .llmtext h4 { margin: 12px 0 4px; }
  #llmFold summary { cursor: pointer; color: var(--muted); margin-top: 6px; }
  .llmhead button.sel, .aihead .ask.sel { border-color: var(--ai); }
  button.small, .aihead .ask { font-size: 12px; padding: 1px 8px; margin-left: auto; background: var(--bg); color: var(--ink);
                               border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
  .aihead { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
  .tcard { margin: 8px 0; padding: 8px 10px; background: var(--bg); border-radius: 6px; font-size: 13px; line-height: 1.7; }
  .aihead .ask.has { background: var(--ai); color: #fff; border-color: var(--ai); }
  .askpanel { position: fixed; top: 0; right: 0; z-index: 1000; width: min(460px, 100vw); height: 100vh; display: flex; flex-direction: column;
          background: var(--panel); border-left: 1px solid var(--line); box-shadow: -6px 0 24px rgba(0,0,0,.18); }
  .askpanel[hidden] { display: none; }  /* (not .chat: Showdown's battle log lines are .chat) */
  @media (max-width: 760px) { .askpanel { top: auto; bottom: 0; left: 0; right: 0; width: auto; height: 78vh; border-left: 0; border-top: 1px solid var(--line);
                                      border-radius: 12px 12px 0 0; box-shadow: 0 -6px 24px rgba(0,0,0,.18); } }
  .askhead { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid var(--line); }
  .askhead b { flex: 1; } .askhead button.small { margin-left: 0; }
  .askhead .x { font-size: 20px; line-height: 1; padding: 0 6px; background: none; border: 0; color: var(--muted); cursor: pointer; }
  .askbody { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .askmsg { max-width: 92%; padding: 8px 10px; border-radius: 10px; font-size: 14px; line-height: 1.6; }
  .askmsg .who { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 2px; }
  .askmsg.me { align-self: flex-end; background: var(--bg); border: 1px solid var(--line); white-space: pre-wrap; }
  .askmsg.ai { align-self: flex-start; border: 1px solid var(--line); border-left: 3px solid var(--ai); }
  .askmsg.ai .llmtext { font-size: 14px; }
  .askfoot { display: flex; gap: 6px; padding: 10px; border-top: 1px solid var(--line); }
  .askfoot textarea { flex: 1; min-width: 0; font: inherit; font-size: 14px; padding: 6px 8px; resize: vertical;
                       background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; }
  .askfoot button { font: inherit; padding: 4px 14px; background: var(--ai); color: #fff; border: 0; border-radius: 6px; cursor: pointer; }
  .llmtext ul, .llmtext ol { margin: 4px 0 4px 20px; padding: 0; } .llmtext blockquote { color: var(--muted); margin: 6px 0; }
  .lines { margin-top: 6px; font-size: 12px; } .lines summary { cursor: pointer; color: var(--muted); }
  .lines ol { margin: 4px 0 4px 18px; padding: 0; } .lines li { margin: 3px 0; }
  .aihead { font-weight: 600; margin-bottom: 4px; }
  .score { display: flex; gap: 12px; flex-wrap: wrap; padding: 0 16px 12px; align-items: stretch; }
  .tile { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 8px 16px; min-width: 130px; }
  .tile b { display: block; font-size: 28px; line-height: 1.2; font-variant-numeric: tabular-nums; }
  .tile b small { font-size: 13px; color: var(--muted); font-weight: 400; margin-left: 4px; }
  .tile span { color: var(--muted); font-size: 12px; } .score .legend { align-self: flex-end; max-width: 360px; }
  .redo { background: var(--ai); color: #fff; border: 0; border-radius: 6px; padding: 4px 12px; cursor: pointer; font: inherit; font-size: 13px; }
  .redobox { margin: 0 16px 12px; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 10px 16px 14px; max-width: 760px; }
  .redobox h3 { margin: 0; font-size: 15px; }
__RF_CSS__
  .lang { margin-left: auto; font-size: 12px; color: var(--muted); }
  .lang button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); padding: 2px 8px; cursor: pointer; font: inherit; }
  .lang button.sel { background: var(--ai); color: #fff; border-color: var(--ai); }
</style>
<header>
  <a class="home" id="home" href="/" hidden></a><h1 id="title"></h1><span class="res" id="res"></span><span class="legend" id="note"></span>
  <button class="redo" id="redo" hidden></button><a class="home" id="other" hidden></a>
  <span class="lang"><span id="lui"></span> <button data-k="ui" data-v="en">EN</button><button data-k="ui" data-v="zh">中文</button>
    &nbsp; <span id="lnames"></span> <button data-k="names" data-v="en">EN</button><button data-k="names" data-v="zh">中文</button></span>
</header>
<div class="score" id="score"></div>
<section class="llmbox" id="llmbox" hidden><div class="llmhead"><b id="llmhead"></b>
  <button data-llm="style"></button><button data-llm="team"></button> <span class="legend" id="llmMsg"></span></div>
  <details id="llmFold" hidden><summary id="llmSum"></summary><div class="llmtext" id="llmText"></div>
    <button id="llmAgain" class="small"></button></details></section>
<aside class="askpanel" id="chat" hidden><div class="askhead"><b id="chatTitle"></b>
  <button id="chatClear" class="small"></button><button id="chatClose" class="x"></button></div>
  <div class="askbody" id="chatBody"></div>
  <div class="askfoot"><textarea id="chatQ" rows="3" maxlength="500"></textarea><button id="chatSend"></button></div></aside>
<section class="redobox" id="redobox" hidden><h3 id="redohead"></h3><div class="legend" id="redonote"></div>
<div class="rf"><label id="whohead"></label><div class="choice" id="who"></div><div class="muted" id="whonote"></div></div>
__RF_HTML__
</section>
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
    <div class="legend" id="rules"></div>
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
__RF_JS__
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
    title: id => `Review · ${id}`, won: "won", lost: "lost", drawn: "tie",
    note: (ms, w) => `Your side: ${R.player || SIDE} (bottom left) | winning chances are the AI search's estimates (${ms} ms × ${w} belief worlds per decision)`,
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
    rules: (z, low, min, big) => `“AI disagrees”: the AI's choice wins at least ${min} points more, the gap beyond ${z}× its error, and either the AI gave your choice under ${low}% of its thinking or the gap is at least ${big} points. “AI doesn't like it”: under ${low}% of its thinking, but the gap is uncertain. A gap under ${min} points is always “acceptable”.`,
    noteRuns: n => n > 1 ? ` × ${n} searches` : "", approx: "≈",
    noteTeam: t => t ? " | your team: pasted (exact)" : " | your team: what the game showed, the rest guessed",
    visits: n => `${n.toLocaleString("en")} visits`,
    redo: "↻ Review again, deeper", redoHead: "Review this game again", whoHead: "Whose decisions",
    llmHead: "AI commentary (a language model, from the review's facts)",
    llmHeadBy: (name, title) => `Commentary by ${name}, ${title} (a language model, from the review's facts)`, llmStyle: "Your playing style", llmAgain: "↻ Write it again",
    llmWorking: "The language model is writing… (up to a minute or two)", llmBusy: "Writing…", llmNoSet: "Set a language model on the home page first.",
    llmShow: k => `${k} (click to open or fold)`, llmTeam: "Your team",
    cardExp: (m, w) => `Against the recent metagame (the matchup model, species only): expected ${m}, against its hardest fifth ${w}`,
    cardThreats: "Hardest of the popular Pokémon (your expected score against teams with it)", cardMembers: n => `Each one's strength in the model (rank of ${n})`,
    cardCover: (a, n, c, exact) => `Opponents' Pokémon the team checks or revenge-kills: ${a} by how often they appear (damage calc over ${n} species, ${c} of all${exact ? "" : "; your unshown sets guessed"})`,
    cardUnanswered: "Nobody answers (by how often they appear)", cardNone: "none",
    cardRare: "Rare counters (worth knowing how to play, not to rebuild for)",
    rareDmg: (m, s, k) => `${m} ${s} (KOs ${k} in one hit)`, rareModel: (m, s, p) => `${m} ${s} (the model: −${p} pts)`,
    cardArch: (st, p, ft) => `Archetype: ${st} (${p} sure)${ft ? " · " + ft : ""}`, cardArchVs: "Against each style",
    cardArchAns: "What beats this style (the model and the games agree)",
    arch: {"stall": "Stall", "balance": "Balance", "bulky offense": "Bulky offense", "hyper offense": "Hyper offense",
           "hazard stack": "Hazard stack", "webs": "Sticky Web", "rain": "Rain", "sun": "Sun", "sand": "Sand", "snow": "Snow",
           "trick room": "Trick Room", "screens": "Screens", "volt-turn": "Volt-turn"},
    cardSynergy: "Pairs the model sees work together or not (points)",
    cardSwaps: "The model's leads for a swap", cardSwap: (o, i, g) => `${o} → ${i} (${g} pts)`,
    cardNote: (g, m) => `From the ladder's games to ${g} and Smogon's ${m} statistics. The matchup model sees species and pairs of teammates, not sets; the threat check is a damage calculation with sets.`,
    askBtn: "Ask the AI", askDefault: "Why the AI sees it so", askLost: "(an earlier question: its words were not kept)",
    askQ1: c => `Why does the AI see this decision so? Was ${c} right?`,
    askQ2: (c, b) => `I chose ${c}; the AI preferred ${b}. What's the difference, and why?`,
    chatTitle: (t, kind) => `Turn ${t} · ${kind}`, chatSend: "Send", chatPh: "Ask about this decision (Enter sends, Shift+Enter a new line)",
    chatFollow: "Ask a follow-up…", chatClear: "Clear", chatClearSure: "Delete this conversation?", chatClose: "Close",
    chatAI: "AI coach", chatYou: "You",
    whoNote: "The other player's view is a review of its own (this one stays); a team pasted is that player's.",
    otherView: n => `↔ ${n}'s view`,
    redoNote: "With more searches, more time or your team pasted; when it is done this page shows the new review (in place of this one).",
    top1: "Matched the AI's first choice", top2: "In the AI's top two", meanLoss: "Average winning chance lost", pts: "pts",
    badMild: "AI disagreed / didn't like it",
    scoreNote: n => `Over your ${n} decisions with a choice; the last tile follows the strictness below.`,
    untried: "untried", left: n => `${n} left`, tera: "terastallized",
    hazMe: "hazards on your side", hazOpp: "on the opponent's side", unseen: x => `You chose ${x} (the log does not show it as such)`,
    switchTo: x => `Switch to ${x}`, teraSuffix: " + Tera", guess: "(guess)", sep: ", ", colon: ": ",
    oppExpect: top => `The AI expected the opponent (a guess: their sets are unknown) to play ${top}.`,
    oppThen: v => ` (your chance then ${v})`, oppDid: (o, v) => `They played ${o}` + (v ? ` (your chance then ${v})` : "") + ".",
    jumpHead: (a, b) => `Why your winning chance went from ${a} to ${b} by the next decision`,
    goodLuck: "Luck for you", badLuck: "Luck against you",
    luckCrit: m => `a critical hit on ${m}`, luckMiss: m => `${m} missed`, luckCant: (m, r) => `${m} could not move (${r})`,
    luckConfused: m => `${m} hurt itself in its confusion`,
    oppBetter: (e, ev, d, dv) => `the opponent's choice was better for you than the AI expected: it expected ${e} (your chance ${ev}), they played ${d} (${dv})`,
    oppWorse: (e, ev, d, dv) => `the opponent's choice was worse for you than the AI expected: it expected ${e} (your chance ${ev}), they played ${d} (${dv})`,
    oppOther: (e, d) => `the opponent did not play what the AI expected most (${e}) but ${d}`,
    jumpUnknown: "no luck in the log, and the opponent played as the AI expected: what this turn revealed (a move, an item, an ability) changed the AI's view",
    youDo: o => `you: ${o}`, theyDo: o => `they: ${o}`, fainted: (m, p) => `${m} fainted (in ${p} of the worlds)`,
    faintSome: p => ` (fainted in ${p} of the worlds)`, lineEnd: v => ` — your chance ${v}`,
    comesIn: (m, hp) => `${m} comes in (${hp})`, noChange: "no change",
    linesHead: "What the AI expects next (its main lines)",
    linesNote: "Each line follows the choices the search looked at most, for your top options and the opponent's likeliest replies; the results are the engine's, over the hidden sets the AI guessed (HP: the median).",
    feared: t => `the line the AI feared: ${t}`,
    guessTip: "The game never showed you using this move: without your team the AI guessed it, and you may not have it.",
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
      "-start": (a, c) => `${cap(a)}: ${c}`, "-end": (a, c) => `${cap(a)}: ${c} ended`, typechange: (a, t) => `${cap(a)} became ${t} type`, "-activate": (a, c) => `${cap(a)}: ${c}`,
      "-singleturn": (a, c) => `${cap(a)}: ${c}`, "-prepare": (a, m) => `${cap(a)} is preparing ${m}`, "-mustrecharge": a => `${cap(a)} must recharge`,
      "-transform": (a, b) => `${cap(a)} transformed into ${b}`, "-formechange": (a, f) => `${cap(a)} changed form: ${f}`, detailschange: (a, f) => `${cap(a)} became ${f}`,
      cant: (a, r) => `${cap(a)} could not move (${r})`, "-message": m => m, win: w => `Winner: ${w}`, tie: () => "A tie",
    },
  },
  zh: {
    title: id => `复盘 · ${id}`, won: "胜", lost: "负", drawn: "平",
    note: (ms, w) => `分析视角：${R.player || SIDE}（左下）｜ 胜率为 AI 搜索的估计（每步 ${ms} ms × ${w} 个信念世界）`,
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
    rules: (z, low, min, big) => `“AI 不认同”：AI 的选择胜率至少高 ${min} 个点，且差距超出误差的 ${z} 倍；同时满足以下之一：AI 对你的选择思考比例低于 ${low}%，或差距至少 ${big} 个点。“AI 不太喜欢”：AI 对你的选择思考比例低于 ${low}%，但差距还不确定。差距不到 ${min} 个点一律算“可以接受”。`,
    noteRuns: n => n > 1 ? ` × ${n} 次搜索` : "", approx: "≈",
    noteTeam: t => t ? " ｜ 我方队伍：已粘贴（精确）" : " ｜ 我方队伍：这局亮出来的部分，其余靠猜",
    visits: n => `访问 ${n.toLocaleString("en")} 次`,
    redo: "↻ 用更强的配置重新分析", redoHead: "重新分析这一局", whoHead: "分析谁的决策",
    llmHead: "AI 解说（语言模型根据复盘数据撰写）",
    llmHeadBy: (name, title) => `${title} ${name} 解说（语言模型根据复盘数据撰写）`, llmStyle: "操作风格评价", llmAgain: "↻ 重新生成",
    llmWorking: "语言模型正在撰写……（可能要一两分钟）", llmBusy: "生成中…", llmNoSet: "请先在首页设置语言模型。",
    llmShow: k => `${k}（点击展开 / 收起）`, llmTeam: "队伍分析",
    cardExp: (m, w) => `对近期环境（对局模型，只看宝可梦种类）：期望胜率 ${m}，对最难打的 20% 对手 ${w}`,
    cardThreats: "最怕的热门宝可梦（对带它的队伍的期望胜率）", cardMembers: n => `每只在模型里的强度排名（共 ${n} 种）`,
    cardCover: (a, n, c, exact) => `队里有人能硬接或先手打倒的对手宝可梦：按出场频率占 ${a}（伤害计算，查了 ${n} 种，占对手出场的 ${c}${exact ? "" : "；没亮出的配置是推测的"}）`,
    cardUnanswered: "没人接得住的（按出场频率）", cardNone: "没有",
    cardRare: "冷门天敌（知道怎么应对就行，不必为它改队）",
    rareDmg: (m, s, k) => `${m} ${s}（一击打倒 ${k} 只）`, rareModel: (m, s, p) => `${m} ${s}（模型：−${p} 点）`,
    cardArch: (st, p, ft) => `流派：${st}（把握 ${p}）${ft ? " · " + ft : ""}`, cardArchVs: "对各风格",
    cardArchAns: "克制这种风格的宝可梦（模型和对局数据一致）",
    arch: {"stall": "受队", "balance": "平衡队", "bulky offense": "重攻队", "hyper offense": "高速进攻队",
           "hazard stack": "钉子队", "webs": "黏网队", "rain": "雨天队", "sun": "晴天队", "sand": "沙暴队", "snow": "雪天队",
           "trick room": "戏法空间队", "screens": "双墙队", "volt-turn": "轮转队"},
    cardSynergy: "模型看到的队友配合（胜率点数）",
    cardSwaps: "模型给出的换人线索", cardSwap: (o, i, g) => `${o} → ${i}（${g} 点）`,
    cardNote: (g, m) => `来自截至 ${g} 的天梯对局和 Smogon ${m} 的统计。对局模型只看宝可梦种类和两两队友配合，看不到配置；威胁检查是按配置做的伤害计算。`,
    askBtn: "问 AI", askDefault: "AI 为什么这样看", askLost: "（较早的提问：问题原文没有保存）",
    askQ1: c => `AI 为什么这样看这一步？我选的${c}对吗？`,
    askQ2: (c, b) => `我选了${c}，AI 更想${b}，差别在哪里，为什么？`,
    chatTitle: (t, kind) => `第 ${t} 回合 · ${kind}`, chatSend: "发送", chatPh: "关于这一步想问什么（回车发送，Shift+回车换行）",
    chatFollow: "继续追问……", chatClear: "清空", chatClearSure: "删除这段对话？", chatClose: "关闭",
    chatAI: "AI 教练", chatYou: "你",
    whoNote: "换成另一位玩家的视角会另存一份复盘（这一份保留）；贴的队伍算那位玩家的。",
    otherView: n => `↔ ${n} 的视角`,
    redoNote: "可以多搜几次、每次多想一会儿，或者贴上你的队伍；完成后这一页会换成新的结果（替换掉现在这份）。",
    top1: "AI 一选吻合率", top2: "AI 前二吻合率", meanLoss: "平均每步胜率损失", pts: "点",
    badMild: "AI 不认同 / 不太喜欢",
    scoreNote: n => `只算有选择余地的 ${n} 步决策；最后一项随下面的判定标准变化。`,
    untried: "未尝试", left: n => `剩 ${n} 只`, tera: "已太晶",
    hazMe: "你这边的钉子", hazOpp: "对手那边的钉子", unseen: x => `你选择了 ${x}（日志里没有按这样显示）`,
    switchTo: x => `换上 ${x}`, teraSuffix: " + 太晶", guess: "（推测）", sep: "、", colon: "：",
    oppExpect: top => `AI 预计对手会（只是推测，AI 不知道对手的配置）：${top}。`,
    oppThen: v => `（你的胜率 ${v}）`, oppDid: (o, v) => `对手实际：${o}` + (v ? `（你的胜率 ${v}）` : "") + "。",
    jumpHead: (a, b) => `为什么到下一步，你的胜率从 ${a} 变成了 ${b}`,
    goodLuck: "对你有利的运气", badLuck: "对你不利的运气",
    luckCrit: m => `${m} 被打出会心一击`, luckMiss: m => `${m} 的招式没有命中`, luckCant: (m, r) => `${m} 无法行动（${r}）`,
    luckConfused: m => `${m} 因混乱攻击了自己`,
    oppBetter: (e, ev, d, dv) => `对手的选择比 AI 预想的对你有利：AI 原以为对手最可能用 ${e}（你的胜率 ${ev}），对手实际用了 ${d}（${dv}）`,
    oppWorse: (e, ev, d, dv) => `对手的选择比 AI 预想的对你不利：AI 原以为对手最可能用 ${e}（你的胜率 ${ev}），对手实际用了 ${d}（${dv}）`,
    oppOther: (e, d) => `对手没有用 AI 最预料的 ${e}，而是用了 ${d}`,
    jumpUnknown: "日志里没有运气因素，对手也按 AI 的预料出招：是这一回合新暴露的招式、道具或特性改变了 AI 的判断",
    youDo: o => `你：${o}`, theyDo: o => `对手：${o}`, fainted: (m, p) => `${m} 倒下（${p} 的世界里）`,
    faintSome: p => `（${p} 的世界里倒下）`, lineEnd: v => ` —— 你的胜率 ${v}`,
    comesIn: (m, hp) => `${m} 上场（${hp}）`, noChange: "没有变化",
    linesHead: "AI 预想的走向（主干路径）",
    linesNote: "每条路径沿着搜索考虑最多的选择往下走：你的前两个选项 × 对手最可能的两个应对。结果由引擎在 AI 猜测的各种对手配置下模拟得出（HP 取中位数）。",
    feared: t => `AI 担心的线路：${t}`,
    guessTip: "这局里你没用过这招：没贴队伍时 AI 只能猜，你可能并没有这招。",
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
      "-start": (a, c) => `${a}：${c}`, "-end": (a, c) => `${a}：${c} 结束`, typechange: (a, t) => `${a} 变成了 ${t} 属性`, "-activate": (a, c) => `${a}：${c}`,
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
    // (a type change -- Protean / Libero, Soak, ...: its new type, as Showdown says it)
    case "-start": if (f[2] == "typechange") return E.typechange(who(f[1]), (f[3] || "").split("/").map(typeName).join("/"));
    case "-end": case "-activate": case "-singleturn": return E[tag](who(f[1]), effect(f[2]));
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
  // (a pivot's switch the log shows without "[from]" -- an Eject Button's, an Emergency Exit's --
  // is a plain switch line: the decision kind is the review's, the turn's choice took its own first;
  // 2026-10-30 review: an Eject Button's switch fell to the turn's end, "not in the log as such")
  const pools = {turn: ["move", "switch", "cant"], "pivot switch": ["pivot", "switch"], "switch after a faint": ["replace"]};
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
// as coach.review.verdict (the page states it: L.rules): "same"; under MIN_LOSS lost "ok"; "bad"
// -- the chance it loses is beyond the noise (Z standard errors; without errors 5 points) and the
// AI hardly thought of the choice, or the loss is at least BIG_LOSS; "mild" -- hardly thought of,
// the loss uncertain; "ok" otherwise
const MIN_LOSS = 0.03, BIG_LOSS = 0.05;
function verdict(d) {
  if (d.chosen == d.best) return "same";
  if (d.loss != null && d.loss < MIN_LOSS) return "ok";  // (2026-10-30: a 1-point gap, paired-sure, read as "bad")
  const unsure = d.repeats > 1 && d.paired != null && d.paired < 2;  // (as coach.review.verdict)
  const real = d.loss != null && !unsure && (d.loss_se ? d.loss > Z * d.loss_se : d.loss >= 0.05);
  const shunned = d.chosen_share < LOW / 100 && d.options[0][1] >= 0.5;
  if (shunned) return real ? "bad" : "mild";
  return real && d.loss >= BIG_LOSS ? "bad" : "ok";
}
const pm = se => se ? ` ±${Math.max(1, Math.round(100 * se))}` : "";
function aiHTML(d) {
  const v = verdict(d), tag = {bad: L.bad, mild: L.mild, same: L.same, ok: L.ok}[v];
  const di = R.decisions.indexOf(d), n = ASKED[di] || 0;
  const ask = LLM_ON ? ` <button class="ask${n ? " has" : ""}${CHAT.dec === di ? " sel" : ""}" data-ask="${di}">${n ? `💬 ${L.askBtn} · ${n}` : L.askBtn}</button>` : "";
  let h = `<div class="aibox"><div class="aihead">${L.aiHead[d.kind] || L.aiHead.turn} <span class="tag ${v == "same" ? "ok" : v}">${tag}</span> <span class="legend">${L.chanceAt(pct(d.value) + pm(d.value_se))}${d.visits ? " · " + L.visits(d.visits) : ""}</span>${ask}</div>`;
  h += `<div class="legend">${L.bars}</div>`;
  h += `<div class="opt head"><span></span><span>${L.winCol}</span><span>${L.shareCol}</span></div>`;
  const opts = d.options.slice();
  if (!opts.some(o => o[0] == d.chosen)) opts.push([d.chosen, d.chosen_share, d.chosen_value, null]);
  const bestSe = (d.options[0] || [])[3];
  for (const row of opts) {
    const [o, share, q, se] = row;
    const cls = o == d.chosen ? "me" : o == d.best ? "ai" : "";
    let diff = "";
    if (q != null && o != d.best) {  // the gap to the AI's choice, "≈" within Z errors
      // (the review's gap and error, from the searches that tried both -- null: too few, "?";
      // older reviews: the means' gap, its error the two combined)
      // (gap: this option's value minus the AI's choice's, negative when worse)
      const paired = row.length >= 6, gap = paired ? (row[4] == null ? null : -row[4]) : q - d.best_value;
      const gse = paired ? row[5] : row.length == 5 ? row[4] : se && bestSe ? Math.hypot(se, bestSe) : null;
      diff = gap == null || (paired && d.repeats > 1 && gse == null) ? "(?)"
        : `(${gse && Math.abs(gap) <= Z * gse ? L.approx : (gap >= 0 ? "+" : "") + Math.round(100 * gap)})`;
    }
    const guess = (d.guessed || []).includes(o) ? ` <span class="guess" title="${esc(L.guessTip)}">${L.guess}</span>` : "";
    h += `<div class="opt"><span class="name ${cls}" title="${esc(o)}">${esc(option(o))}${guess}</span>
      <span class="bar"><span class="win" style="width:${q == null ? 0 : 100 * q}%"></span></span>
      ${q == null ? `<span class="num" style="grid-column: span 3">${L.untried}</span>`
        : `<span class="num">${pct(q)}</span><span class="se">${pm(se).trim()}</span><span class="diff">${diff}</span>`}
      <span class="bar"><span class="share" style="width:${100 * share}%"></span></span>
      <span class="num">${pct(share)}</span></div>`;
  }
  const st = d.state, me = st.me, op = st.opp;
  const b = x => Object.entries(x || {}).map(([k, v]) => (ST[k] || k) + " " + (v > 0 ? "+" + v : v)).join(", ");
  const sideText = (s, label) => `${label}: ${esc(monName(s.active.species))} ${pct(s.active.hp)}${Object.keys(s.boosts || {}).length ? " (" + b(s.boosts) + ")" : ""} · ${L.left(s.alive)}${s.tera_used ? " · " + L.tera : ""}`;
  h += `<div class="state">${sideText(me, L.you)} | ${sideText(op, L.opp)}${Object.keys(me.hazards).length ? " | " + L.hazMe + ": " + b(me.hazards) : ""}${Object.keys(op.hazards).length ? " | " + L.hazOpp + ": " + b(op.hazards) : ""}</div>`;
  return h + oppHTML(d) + jumpHTML(d) + linesHTML(d) + "</div>";
}
// the search's principal variations (the review's lines, as KataGo's variations): each step's
// choices and what the worlds made of them -- the actives' HP (median) and how often one fainted
// (only what changed, from the decision's actives on: a mon coming in with its HP, an HP change
// as before -> after, a faint; 2026-10-30, every step's HP read as damage -- a Dragapult's 48% it
// had had for turns)
function stepText(st, prev) {
  const act = [st.o != "No Move" ? L.youDo(oppName(st.o)) : null, st.t != "No Move" ? L.theyDo(oppName(st.t)) : null].filter(Boolean).join(L.sep);
  const mon = ([sp, hp, faint], mine) => {
    const name = esc(mine ? L.mine(monName(sp)) : L.theirs(monName(sp))), was = prev[mine ? "me" : "opp"];
    if (faint >= 0.5) return L.fainted(name, pct(faint));
    const some = faint > 0 ? L.faintSome(pct(faint)) : "";
    if (!was || was[0] != sp) return L.comesIn(name, pct(hp)) + some;
    return Math.abs(hp - was[1]) >= 0.01 ? `${name} ${pct(was[1])}→${pct(hp)}` + some : some ? name + some : "";
  };
  const res = [mon(st.me, true), mon(st.opp, false)].filter(Boolean).join(L.sep);
  prev.me = st.me; prev.opp = st.opp;
  return `${act} ⇒ ${res || L.noChange}`;
}
function lineText(line, d) {
  const a = ((d || {}).state || {}), key = x => x && x.active ? [String(x.active.species).toLowerCase(), x.active.hp] : null;
  const prev = {me: key(a.me), opp: key(a.opp)};
  return line.map(st => stepText(st, prev)).join(" → ") + (line.length && line[line.length - 1].v != null ? L.lineEnd(pct(line[line.length - 1].v)) : "");
}
function linesHTML(d) {
  if (!d.lines || !d.lines.length) return "";
  return `<details class="lines"><summary>${L.linesHead}</summary><ol>${d.lines.map(l => `<li>${lineText(l, d)}</li>`).join("")}</ol><div class="legend">${L.linesNote}</div></details>`;
}
// the opponent as the search saw it (the review's opp_options: share, our chance if it takes
// it -- a guess from the player's view, the opponent's sets unknown) and what it did that turn
const JUMP = 0.15;  // a change of the winning chance by the next decision that the page explains
const oppName = o => esc(option(o));
function oppHTML(d) {
  const opts = d.opp_options || [];
  if (!opts.length) return "";
  const top = opts.slice(0, 3).filter(o => o[1] >= 0.01).map(([o, s, q]) => `${oppName(o)} ${pct(s)}` + (q != null ? L.oppThen(pct(q)) : "")).join(L.sep);
  const did = d.opp_did, dq = did ? (opts.find(o => o[0] == did) || [])[2] : null;
  return `<div class="legend opp">${L.oppExpect(top)}${did ? " " + L.oppDid(oppName(did), dq != null ? pct(dq) : null) : ""}</div>`;
}
// the turn's luck as the log shows it: [what, good for the player]
function luck(t) {
  const out = [];
  for (const line of R.events[t] || []) {
    const f = line.split("|"), tag = f[0], mine = (f[1] || "").startsWith("ME"), mon = esc(who(f[1]) || "");
    if (tag == "-crit") out.push([L.luckCrit(mon), !mine]);  // (a critical hit on that mon)
    else if (tag == "-miss") out.push([L.luckMiss(mon), !mine]);  // (that mon missed)
    else if (tag == "cant" && ["par", "flinch", "frz"].includes(f[2])) out.push([L.luckCant(mon, esc(effect(f[2]) || f[2])), !mine]);
    else if (tag == "-damage" && line.includes("[from] confusion")) out.push([L.luckConfused(mon), !mine]);
  }
  return out;
}
// a big change of the winning chance by the next decision, explained: the turn's luck, the
// opponent's choice against what the search expected, else what the turn showed
function jumpHTML(d) {
  if (d.kind != "turn") return "";
  const n = R.decisions[R.decisions.indexOf(d) + 1];
  if (!n || Math.abs(n.value - d.value) < JUMP) return "";
  const items = luck(d.turn).map(([what, good]) => `${good ? L.goodLuck : L.badLuck}${L.colon}${what}`);
  const opts = d.opp_options || [], exp = opts[0];
  if (d.opp_did && exp && exp[0] != d.opp_did) {
    // (only a choice that moved your chance -- 5 points or more from the expected one's; one the
    // search never tried: said as such)
    const did = opts.find(o => o[0] == d.opp_did), q = did ? did[2] : null;
    if (q == null || exp[2] == null) items.push(L.oppOther(oppName(exp[0]), oppName(d.opp_did)));
    else if (Math.abs(q - exp[2]) >= 0.05) items.push((q > exp[2] ? L.oppBetter : L.oppWorse)(oppName(exp[0]), pct(exp[2]), oppName(d.opp_did), pct(q)));
    // (the line the search expected after your choice and that reply: why it mattered)
    const line = (d.lines || []).find(l => l.length && l[0].o == d.chosen && l[0].t == exp[0]);
    if (line && items.length) items.push(L.feared(lineText(line, d)));
  }
  if (!items.length) items.push(L.jumpUnknown);
  return `<div class="jump"><b>${L.jumpHead(pct(d.value), pct(n.value))}</b><ul>${items.map(x => `<li>${x}</li>`).join("")}</ul></div>`;
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
document.title = L.title(R.title || R.id);
document.documentElement.lang = UI == "zh" ? "zh" : "en";
document.getElementById("title").textContent = L.title(R.title || R.id);
if (location.protocol.startsWith("http")) { const a = document.getElementById("home"); a.textContent = L.home; a.hidden = false; }
document.getElementById("res").textContent = R.won == null ? L.drawn : R.won ? L.won : L.lost;
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
  const show = () => {
    out.textContent = id == "z" ? L.tzv(get()) : L.tlv(get());
    document.getElementById("rules").textContent = L.rules(Z, LOW, Math.round(100 * MIN_LOSS), Math.round(100 * BIG_LOSS));
  };
  el.value = get(); show();
  el.addEventListener("input", () => { set(parseFloat(el.value)); show(); try { localStorage.setItem("coach-" + id, el.value); } catch (e) {} render(); });
}
// "review again" (served by the app: /api/redo-info answers): the home page's form, set one step
// deeper than this review (fast -> standard -> deep; deep and custom stay deep -- custom, its
// fields filled in with two more searches, only when picked), the team pasted
// before kept; when done the page reloads with the new review
const DIR = (location.pathname.match(/\/coach\/([^/]+)\/viewer\.html$/) || [])[1];
// the AI commentary (coach.llm, served by the app): a write-up kept with the review is shown,
// a new one asked for and polled; the model's Markdown shown as text (escaped, a few marks kept)
function md(text) {
  const inline = x => esc(x).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  let out = "", list = null;
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (const raw of text.split("\n")) {
    const line = raw.trim(), h = line.match(/^#{1,4}\s+(.*)$/), ul = line.match(/^[-*]\s+(.*)$/), ol = line.match(/^\d+[.)]\s+(.*)$/);
    if (h) { close(); out += `<h4>${inline(h[1])}</h4>`; }
    else if (ul || ol) { const k = ul ? "ul" : "ol"; if (list != k) { close(); out += `<${k}>`; list = k; } out += `<li>${inline((ul || ol)[1])}</li>`; }
    else if (line.startsWith(">")) { close(); out += `<blockquote>${inline(line.replace(/^>\s*/, ""))}</blockquote>`; }
    else if (line) { close(); out += `<p>${inline(line)}</p>`; }
    else close();
  }
  close();
  return out;
}
// a write-up asked for and polled: its text (the error thrown)
async function llmAsk(body) {
  const r = await fetch("/api/llm", {method: "POST", headers: {"Content-Type": "application/json"},
                                      body: JSON.stringify({review: DIR, lang: UI, ...body})});
  const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText);
  for (;;) {
    await new Promise(res => setTimeout(res, 2000));
    const s = await (await fetch("/api/job/" + j.job)).json();
    if (s.status == "done") return s.text;
    if (s.status == "error") throw new Error(s.error);
  }
}
const llmGet = q => fetch(`/api/llm?review=${encodeURIComponent(DIR)}&lang=${UI}&${q}`).then(r => r.ok ? r.json() : null);
const LLM_ON = location.protocol.startsWith("http") && !!DIR;
if (LLM_ON) {
  // the top bar: the style and the team write-ups, one fold showing the one picked (folded on
  // load: a write-up is long, the replay under it; open when just written)
  const box = document.getElementById("llmbox"), msg = document.getElementById("llmMsg"), out = document.getElementById("llmText");
  const fold = document.getElementById("llmFold"), again = document.getElementById("llmAgain"), sum = document.getElementById("llmSum");
  const TEXT = {}, btns = [...document.querySelectorAll("[data-llm]")];
  let shown = null;
  document.getElementById("llmhead").textContent = L.llmHead; again.textContent = L.llmAgain;
  // (the coach chosen on the home page: "<title> <name>'s commentary"; none: the plain heading)
  fetch("/api/llm-settings").then(r => r.ok ? r.json() : null).then(s => {
    const p = s && (s.personas || []).find(x => x[0] == s.persona && x[0] != "none");
    if (p) document.getElementById("llmhead").textContent = UI == "zh" ? L.llmHeadBy(p[2], p[4]) : L.llmHeadBy(p[1], p[3]);
  }).catch(() => {});
  const label = k => (k == "style" ? L.llmStyle : L.llmTeam) + (TEXT[k] ? " ✓" : "");
  const relabel = () => btns.forEach(b => { b.textContent = label(b.dataset.llm); b.classList.toggle("sel", b.dataset.llm == shown && !fold.hidden); });
  // (the team's: the metagame's numbers first -- coach.meta, no language model -- the write-up under them)
  let CARD = null;
  const card = () => {
    const f = CARD && CARD.facts; if (!f) return "";
    const p = x => pct(x), mon = s => esc(monName(s.replace("-*", "")));
    const th = f.threats_worst.slice(0, 3).map(t => `${mon(t.species)} ${p(t.score_vs_teams_with_it)}`).join(L.sep);
    const mem = f.members.map(m => `${mon(m.species)} ${m.model_strength_rank ? "#" + m.model_strength_rank : "—"}`).join(L.sep);
    const sw = f.swaps.slice(0, 2).map(s => L.cardSwap(mon(s.out), mon(s.in), (s.gain >= 0 ? "+" : "") + Math.round(100 * s.gain))).join(L.sep);
    const syn = (f.synergy || []).map(x => `${mon(x.pair[0])} + ${mon(x.pair[1])} ${x.points > 0 ? "+" : ""}${x.points}`).join(L.sep);
    const tc = f.threat_coverage, sh = x => (100 * x).toFixed(x < 0.01 ? 1 : 0) + "%";
    const un = tc ? tc.unanswered.slice(0, 5).map(x => `${mon(x.threat)} ${sh(x.share)}`).join(L.sep) : "";
    // (rare counters: the damage check's and the model's, rare ones only, each once)
    const rare = [], seen = new Set();
    for (const x of (tc ? tc.rare_counters : [])) { seen.add(x.threat); rare.push(L.rareDmg(mon(x.threat), sh(x.share), x.kos_in_one_hit.length)); }
    for (const x of (f.counters_by_model || [])) if (x.share < 0.005 && x.points_against_you >= 1 && !seen.has(x.species)) rare.push(L.rareModel(mon(x.species), sh(x.share), x.points_against_you));
    // (the archetype: teams.archetypes via coach.meta -- its style, features, chances by the style met;
    // its answers when the model (>= 0.05 logit) and the games (>= 0.5 points) agree)
    const ar = f.archetype, an = k => esc(L.arch[k] || k);
    const arch = ar ? `<div>${L.cardArch(an(ar.style), p(ar.style_probs[ar.style]), ar.features.map(an).join(L.sep))}</div>
      ${ar.your_score_by_opponent_style ? `<div>${L.cardArchVs}${L.colon}${Object.entries(ar.your_score_by_opponent_style).map(([k, v]) => `${an(k)} ${p(v.expected)}`).join(L.sep)}</div>` : ""}
      ${(((ar.metagame || {})[ar.style] || {}).answers || []).some(x => x.model_logit >= 0.05 && x.games_lift >= 0.005)
        ? `<div>${L.cardArchAns}${L.colon}${ar.metagame[ar.style].answers.filter(x => x.model_logit >= 0.05 && x.games_lift >= 0.005).slice(0, 4).map(x => mon(x.species)).join(L.sep)}</div>` : ""}` : "";
    return `<div class="tcard"><div><b>${L.cardExp(p(f.expected_vs_metagame), p(f.worst_20pct_of_metagame))}</b></div>${arch}
      <div>${L.cardThreats}${L.colon}${th}</div><div>${L.cardMembers(f.members[0].of)}${L.colon}${mem}</div>
      ${tc ? `<div>${L.cardCover(sh(tc.answered_share), tc.checked, sh(tc.checked_share), tc.your_sets_exact)}</div>
             <div>${L.cardUnanswered}${L.colon}${un || L.cardNone}</div>` : ""}
      ${rare.length ? `<div>${L.cardRare}${L.colon}${rare.slice(0, 4).join(L.sep)}</div>` : ""}
      ${syn ? `<div>${L.cardSynergy}${L.colon}${syn}</div>` : ""}
      ${sw ? `<div>${L.cardSwaps}${L.colon}${sw}</div>` : ""}<div class="legend">${L.cardNote(esc(f.about.games_to), esc(f.about.smogon_month))}</div></div>`;
  };
  const show = (k, open) => { shown = k; out.innerHTML = (k == "team" ? card() : "") + (TEXT[k] ? md(TEXT[k]) : "");
                              sum.textContent = L.llmShow(k == "style" ? L.llmStyle : L.llmTeam);
                              fold.hidden = false; fold.open = open; relabel(); };
  fetch(`/api/team-facts?review=${encodeURIComponent(DIR)}`).then(r => r.ok ? r.json() : null).then(j => { CARD = j; if (shown == "team") show("team", fold.open); });
  // (while writing: the old text cleared for a "writing" line, every button greyed, this one saying
  // so -- 2026-10-30, a regeneration showed no change for a minute; the old text back on a failure)
  const make = async k => {
    const old = TEXT[k];
    btns.forEach(b => { b.disabled = true; }); again.disabled = true; again.textContent = L.llmBusy; msg.textContent = "";
    delete TEXT[k]; show(k, true); out.insertAdjacentHTML("beforeend", `<div class="llmwait">${L.llmWorking}</div>`);
    try { TEXT[k] = await llmAsk({kind: k}); }
    catch (e) { if (old) TEXT[k] = old; msg.textContent = e.message; }
    show(k, true); btns.forEach(b => { b.disabled = false; }); again.disabled = false; again.textContent = L.llmAgain;
  };
  Promise.all(["style", "team"].map(k => llmGet("kind=" + k).then(j => { if (j && j.text) TEXT[k] = j.text; return j; }))).then(js => {
    if (!js.some(Boolean)) return;
    box.hidden = false; relabel();
    const k = ["style", "team"].find(k => TEXT[k]); if (k) show(k, false);
  });
  btns.forEach(b => { b.onclick = () => { const k = b.dataset.llm; if (TEXT[k]) { show(k, true); } else { if (k == "team") show(k, true); make(k); } }; });
  again.onclick = () => { if (shown) make(shown); };
}
// "ask the AI" (2026-10-30): a side panel with the decision's conversation (coach.llm.thread) --
// a question ready to send or edit, follow-ups, closed at will; the page stays as long as it was.
// CHAT: the decision shown (null: closed), each decision's messages, busy, the error; ASKED: each
// decision's count of questions and answers, on its button
const CHAT = {dec: null, msgs: {}, busy: false, asking: null, error: null}, ASKED = {};
function chatDefault(i) {
  const d = R.decisions[i];
  return d.chosen == d.best || !d.best ? L.askQ1(option(d.chosen)) : L.askQ2(option(d.chosen), option(d.best));
}
function chatRender() {
  const box = document.getElementById("chat"), i = CHAT.dec;
  if (i === null) { box.hidden = true; return; }
  const d = R.decisions[i], msgs = CHAT.msgs[i] || [];
  box.hidden = false;
  document.getElementById("chatTitle").textContent = L.chatTitle(d.turn, L.aiHead[d.kind] || L.aiHead.turn);
  let h = "";
  for (const m of msgs) {
    const q = m.question === null ? L.askDefault : m.question === "" ? L.askLost : m.question;
    const who = m.coach ? m.coach[UI == "zh" ? 1 : 0] : L.chatAI;
    h += `<div class="askmsg me"><div class="who">${L.chatYou}</div>${esc(q)}</div>
      <div class="askmsg ai"><div class="who">${esc(who)}</div><div class="llmtext">${md(m.answer)}</div></div>`;
  }
  if (CHAT.busy) h += `<div class="askmsg me"><div class="who">${L.chatYou}</div>${esc(CHAT.asking)}</div><div class="askmsg ai"><div class="llmwait">${L.llmWorking}</div></div>`;
  if (CHAT.error) h += `<div class="legend">${esc(CHAT.error)}</div>`;
  const body = document.getElementById("chatBody");
  body.innerHTML = h; body.scrollTop = body.scrollHeight;
  const q = document.getElementById("chatQ"), send = document.getElementById("chatSend");
  q.placeholder = msgs.length ? L.chatFollow : L.chatPh;
  send.disabled = CHAT.busy; send.textContent = CHAT.busy ? L.llmBusy : L.chatSend;
  document.getElementById("chatClear").hidden = !msgs.length || CHAT.busy;
}
async function chatOpen(i) {
  const q = document.getElementById("chatQ");
  if (CHAT.dec !== i) { CHAT.error = null; q.value = ""; }
  CHAT.dec = i; render(); chatRender();
  if (!CHAT.msgs[i]) {
    const j = await llmGet(`kind=turn&dec=${i}&all=1`);
    CHAT.msgs[i] = j && j.thread || []; ASKED[i] = CHAT.msgs[i].length;
  }
  if (!CHAT.msgs[i].length && !q.value) q.value = chatDefault(i);  // (a question ready: edit or send)
  chatRender(); q.focus();
}
function chatClose() { CHAT.dec = null; chatRender(); render(); }
async function chatSend() {
  const i = CHAT.dec, q = document.getElementById("chatQ"), text = q.value.trim();
  if (i === null || CHAT.busy || !text) return;
  CHAT.busy = true; CHAT.asking = text; CHAT.error = null; q.value = ""; chatRender();
  try {
    await llmAsk({kind: "turn", dec: i, question: text});
    const j = await llmGet(`kind=turn&dec=${i}&all=1`);
    CHAT.msgs[i] = j && j.thread || []; ASKED[i] = CHAT.msgs[i].length;
  } catch (err) { CHAT.error = err.message; if (!q.value) q.value = text; }
  CHAT.busy = false; chatRender(); render();
}
if (LLM_ON) {
  document.getElementById("chatClose").textContent = "×";
  document.getElementById("chatClose").title = L.chatClose;
  document.getElementById("chatClear").textContent = L.chatClear;
  document.getElementById("chatClose").onclick = chatClose;
  document.getElementById("chatSend").onclick = chatSend;
  document.getElementById("chatClear").onclick = async () => {
    const i = CHAT.dec;
    if (i === null || !confirm(L.chatClearSure)) return;
    try { await fetch("/api/llm-clear", {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify({review: DIR, dec: i, lang: UI})}); } catch (e) {}
    CHAT.msgs[i] = []; ASKED[i] = 0; document.getElementById("chatQ").value = chatDefault(i); chatRender(); render();
  };
  document.getElementById("chatQ").addEventListener("keydown", e => {
    if (e.key == "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); chatSend(); }
  });
  document.addEventListener("click", e => {
    const open = e.target.closest("[data-ask]");
    if (open) { const i = +open.dataset.ask; if (CHAT.dec === i) chatClose(); else chatOpen(i); }
  });
  llmGet("asked=1").then(j => { if (j && j.asked) { Object.assign(ASKED, j.asked); render(); } });
  // (a link to a decision's conversation: #ask=<decision index>)
  const deep = /^#ask=(\d+)$/.exec(location.hash);
  if (deep && R.decisions[+deep[1]]) setTimeout(() => chatOpen(+deep[1]), 0);
}
if (location.protocol.startsWith("http") && DIR) {
  fetch("/api/redo-info?review=" + encodeURIComponent(DIR)).then(r => r.ok ? r.json() : null).then(info => {
    if (!info) return;
    const btn = document.getElementById("redo"), box = document.getElementById("redobox");
    btn.textContent = L.redo; btn.hidden = false;
    const otherName = info.players.find(p => p && p != info.player);
    if (info.other && otherName) {
      const a = document.getElementById("other"); a.href = info.other; a.textContent = L.otherView(otherName); a.hidden = false;
    }
    document.getElementById("whohead").textContent = L.whoHead; document.getElementById("whonote").textContent = L.whoNote;
    document.getElementById("who").innerHTML = info.players.map(p => p ?
      `<label><input type="radio" name="rf-who" value="${esc(p).replace(/"/g, "&quot;")}" ${p == info.player ? "checked" : ""} /> ${esc(p)}</label>` : "").join("");
    const who = () => (document.querySelector("input[name=rf-who]:checked") || {}).value || info.player;
    document.getElementById("redohead").textContent = L.redoHead; document.getElementById("redonote").textContent = L.redoNote;
    let form = null;
    btn.onclick = () => {
      box.hidden = !box.hidden;
      if (form || box.hidden) return;
      const order = ["fast", "standard", "deep"], cur = [R.worlds, R.ms, R.repeats || 1].join();
      const at = order.findIndex(k => (info.strengths[k] || []).join() == cur);
      form = reviewForm(UI, info, {
        decisions: () => info.decisions[Math.max(0, info.players.indexOf(who()))],
        // (one step deeper, deep at most: custom only when the person picks it -- 2026-10-30, a
        // deep review's "review again" opened on custom, seven searches x 3 s)
        preset: at >= 0 && at < 2 ? order[at + 1] : "deep",
        custom: [R.worlds, R.ms / 1000, Math.min(8, (R.repeats || 1) + 2)], keptTeam: () => info.team && who() == info.player,
        submit: async v => {
          const r = await fetch("/api/redo", {method: "POST", headers: {"Content-Type": "application/json"},
                                              body: JSON.stringify({...v, review: DIR, player: who(), lang: UI})});
          const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j.job;
        },
        done: url => { if (url == location.pathname) location.reload(); else location.href = url; },
      });
      document.querySelectorAll("input[name=rf-who]").forEach(x => { x.onchange = form.estimate; });
      box.scrollIntoView({block: "nearest"});
    };
  }).catch(() => {});
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
  // (not while typing: the arrows and "m" belong to the field -- 2026-10-30, the ask box's
  // left / right moved the replay; Esc closes the "ask the AI" panel)
  const t = e.target;
  if (e.key == "Escape" && CHAT.dec !== null) { chatClose(); return; }
  if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
  if (e.altKey || e.ctrlKey || e.metaKey) return;
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


def render(report: dict, row: dict, client: str = "official", title: str | None = None) -> str:
    """The review page of ``report`` (coach.review) for the replay ``row``; ``client``: "official"
    (Showdown's site serves the player: open the file directly) or "local" (our server,
    coach.server: open http://127.0.0.1:<port>/coach/<review>/viewer.html); ``title``: the name
    the person gave it (coach.index; else the replay's id)."""
    events = turn_events(row["log"], report["side"])  # (from the log: the current wording)
    ds = [{k: v for k, v in d.items() if k != "events"} | {"score": round(mistake_score(d), 3)}
          for d in report["decisions"]]  # fmt: skip
    # (the verdicts and the moments: computed by the page, its thresholds adjustable)
    won = None if report["winner"] not in ("p1", "p2") else report["winner"] == report["side"]
    data = {"id": report["id"], "title": title or "", "side": report["side"], "player": report.get("player"), "won": won, "turns": report["turns"],
            "ms": report["settings"]["ms"], "worlds": report["settings"]["worlds"],
            "decisions": ds, "events": events, "repeats": report["settings"].get("repeats", 1),
            "team": report["settings"].get("team", False), "last_turn": max(events)}  # fmt: skip
    log = row["log"].replace("</", "<\\/")
    return (form.embed(PAGE).replace("__REVIEW__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__LOG__", log)
            .replace("__PLAYER__", LOCAL if client == "local" else OFFICIAL))  # fmt: skip
