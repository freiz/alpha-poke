"""A game review as one HTML page (2026-10-29): Showdown's own replay player (sprites,
animations: its replay-embed.js, MIT, loaded from play.pokemonshowdown.com -- the client's look
and data stay current without us) next to the review: the winning-chance curve with the
mistakes marked, each decision's options (the search's winning chance and share of visits), the
player's choice and the search's; previous / next decision, next mistake, the keyboard; the
player and the panel follow each other (Battle.seekTurn / subscribe). Open it in a browser (a
local file: it needs the internet for the player's scripts and sprites)."""

import json

from alpha_poke.coach.review import key_moments, mistake_score, turn_events

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Game review</title>
<style>
  :root { --bg: #f5f6f8; --panel: #ffffff; --ink: #1d2330; --muted: #677085; --line: #d9dde5;
          --good: #2f9e5b; --bad: #d64545; --ai: #3567d6; --me: #e08a1e; }
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
  .tag.bad { background: var(--bad); color: #fff; } .tag.ok { background: var(--good); color: #fff; }
  .opt { display: grid; grid-template-columns: 170px 1fr 48px; gap: 8px; align-items: center; margin: 3px 0; }
  .opt .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .opt .name.me { color: var(--me); font-weight: 600; } .opt .name.ai { color: var(--ai); font-weight: 600; }
  .bars { position: relative; height: 18px; background: var(--bg); border-radius: 4px; overflow: hidden; }
  .bars .win { position: absolute; left: 0; top: 0; bottom: 6px; background: var(--ai); opacity: .75; }
  .bars .share { position: absolute; left: 0; bottom: 0; height: 4px; background: var(--muted); }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .legend, .state, .events { color: var(--muted); font-size: 12px; }
  .events { white-space: pre-wrap; margin-top: 6px; max-height: 120px; overflow: auto; }
  .moments li { cursor: pointer; margin: 2px 0; } .moments li:hover { color: var(--ai); }
  .none { color: var(--muted); padding: 10px 0; }
  .lang { margin-left: auto; font-size: 12px; color: var(--muted); }
  .lang button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); padding: 2px 8px; cursor: pointer; font: inherit; }
  .lang button.sel { background: var(--ai); color: #fff; border-color: var(--ai); }
</style>
<header>
  <h1 id="title"></h1><span class="res" id="res"></span><span class="legend" id="note"></span>
  <span class="lang"><span id="lui"></span> <button data-k="ui" data-v="en">EN</button><button data-k="ui" data-v="zh">中文</button>
    &nbsp; <span id="lnames"></span> <button data-k="names" data-v="en">EN</button><button data-k="names" data-v="zh">中文</button></span>
</header>
<main>
  <div class="wrapper replay-wrapper">
    <div class="battle"></div><div class="battle-log"></div>
    <div class="replay-controls"></div><div class="replay-controls-2"></div>
  </div>
  <section id="panel">
    <svg id="curve" viewBox="0 0 600 150" preserveAspectRatio="none"></svg>
    <div class="legend" id="curvenote"></div>
    <div class="nav">
      <button data-go="first"></button><button data-go="prev"></button>
      <button data-go="next"></button><button data-go="mistake"></button>
    </div>
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
       brn: "burned", par: "paralyzed", slp: "asleep", frz: "frozen", psn: "poisoned", tox: "badly poisoned"},
  zh: {atk: "攻击", def: "防御", spa: "特攻", spd: "特防", spe: "速度", accuracy: "命中率", evasion: "闪避率",
       attack: "攻击", defense: "防御", special_attack: "特攻", special_defense: "特防", speed: "速度",
       stealth_rock: "隐形岩", spikes: "撒菱", toxic_spikes: "毒菱", sticky_web: "黏黏网",
       brn: "灼伤", par: "麻痹", slp: "睡眠", frz: "冰冻", psn: "中毒", tox: "剧毒"},
};
const T = {
  en: {
    title: id => `Review · ${id}`, won: "won", lost: "lost",
    note: (ms, w) => `Your side: ${SIDE == "p1" ? "p1 (bottom left)" : "p2"} | winning chances are the AI search's estimates (${ms} ms × ${w} belief worlds per decision)`,
    ui: "Interface", names: "Names",
    curve: "Your winning chance at each of your decisions (red: the AI clearly disagreed). Click a point to jump there; ←/→ previous / next, M next mistake.",
    first: "⏮ Start", prev: "◀ Previous", next: "Next ▶", mistake: "⚠ Next mistake",
    momentsHead: "Where the AI disagreed most", noMoments: "No clear mistakes.", noDecision: "No decision of yours this turn.",
    turn: t => `Turn ${t}`, kinds: {"pivot switch": " (switch after a pivot move)", "switch after a faint": " (switch after a faint)"},
    now: "winning chance", bad: "AI disagrees", same: "same as the AI", ok: "acceptable",
    bars: `Bar: winning chance after the option; thin bar: the AI's share of thinking. <span style="color:var(--me)">Orange</span> = your choice, <span style="color:var(--ai)">blue</span> = the AI's.`,
    untried: "untried", you: "You", opp: "Opponent", left: n => `${n} left`, tera: "terastallized",
    hazMe: "hazards on your side", hazOpp: "on the opponent's side", happened: "What happened this turn:",
    switchTo: x => `Switch to ${x}`, teraSuffix: " + Tera",
    moment: (t, c, b, cv, bv) => `Turn ${t}: you chose <b>${c}</b>, the AI <b>${b}</b> (${cv} → ${bv})`,
    mine: x => `your ${x}`, theirs: x => `the opposing ${x}`, side: me => me ? "your side" : "the opposing side",
    ev: {
      move: (a, m, t) => `${cap(a)} used ${m}` + (t && t != a ? ` on ${t}` : ""), switch: a => `${cap(a)} came in`, drag: a => `${cap(a)} was dragged in`,
      faint: a => `${cap(a)} fainted`, "-supereffective": a => `→ super effective on ${a}`, "-resisted": a => `→ ${a} resisted it`,
      "-immune": (a, f) => `→ ${a} is immune` + (f ? ` (${f})` : ""), "-crit": () => "→ a critical hit", "-miss": a => `${cap(a)} missed`,
      "-terastallize": (a, t) => `${cap(a)} terastallized into ${t}`, "-boost": (a, s, n) => `${cap(a)}'s ${s} rose by ${n}`,
      "-unboost": (a, s, n) => `${cap(a)}'s ${s} fell by ${n}`, "-sidestart": (sd, c) => `${cap(sd)}: ${c} set`, "-sideend": (sd, c) => `${cap(sd)}: ${c} removed`,
      "-enditem": (a, i, f) => `${cap(a)} lost its ${i}` + (f ? ` (${f})` : ""), "-item": (a, i) => `${cap(a)} holds ${i}`,
      "-ability": (a, ab) => `${cap(a)}'s ${ab}`, "-status": (a, st) => `${cap(a)} is ${st}`, "-damage": (a, hp) => `${cap(a)}: ${hp} HP`,
      cant: (a, r) => `${cap(a)} could not move (${r})`, win: w => `Winner: ${w}`,
    },
  },
  zh: {
    title: id => `复盘 · ${id}`, won: "胜", lost: "负",
    note: (ms, w) => `分析视角：${SIDE == "p1" ? "p1（左下）" : "p2"} ｜ 胜率为 AI 搜索的估计（每步 ${ms} ms × ${w} 个信念世界）`,
    ui: "界面", names: "名称",
    curve: "你每次决策时的胜率（红点：AI 明显不认同的决策）。点击曲线跳到该处；←/→ 上一步 / 下一步，M 下一个失误。",
    first: "⏮ 开局", prev: "◀ 上一步", next: "下一步 ▶", mistake: "⚠ 下一个失误",
    momentsHead: "AI 最不认同的决策", noMoments: "没有明显的失误。", noDecision: "这一回合你没有需要做的决策。",
    turn: t => `回合 ${t}`, kinds: {"pivot switch": "（折返换人）", "switch after a faint": "（倒下后换人）"},
    now: "当前胜率", bad: "AI 不认同", same: "和 AI 一致", ok: "可以接受",
    bars: `长条：选这一步后的胜率；底部细条：AI 搜索在这一步上花的比例。<span style="color:var(--me)">橙色</span>=你的选择，<span style="color:var(--ai)">蓝色</span>=AI 的选择`,
    untried: "未尝试", you: "你", opp: "对手", left: n => `剩 ${n} 只`, tera: "已太晶",
    hazMe: "你这边的钉子", hazOpp: "对手那边的钉子", happened: "这一回合发生了什么：",
    switchTo: x => `换上 ${x}`, teraSuffix: " + 太晶",
    moment: (t, c, b, cv, bv) => `回合 ${t}：你选了 <b>${c}</b>，AI 选 <b>${b}</b>（${cv} → ${bv}）`,
    mine: x => `你的 ${x}`, theirs: x => `对手的 ${x}`, side: me => me ? "你这一侧" : "对手那一侧",
    ev: {
      move: (a, m, t) => `${a} 使用了 ${m}` + (t && t != a ? `（对 ${t}）` : ""), switch: a => `${a} 上场`, drag: a => `${a} 被强制换上场`,
      faint: a => `${a} 倒下了`, "-supereffective": a => `→ 对 ${a} 效果绝佳`, "-resisted": a => `→ ${a} 抵抗了（效果不好）`,
      "-immune": (a, f) => `→ ${a} 免疫` + (f ? `（${f}）` : ""), "-crit": () => "→ 击中要害（暴击）", "-miss": a => `${a} 的招式没有命中`,
      "-terastallize": (a, t) => `${a} 太晶化为 ${t} 属性`, "-boost": (a, s, n) => `${a} 的${s}提升 ${n} 级`,
      "-unboost": (a, s, n) => `${a} 的${s}下降 ${n} 级`, "-sidestart": (sd, c) => `${sd}被放了 ${c}`, "-sideend": (sd, c) => `${sd}的 ${c} 被清除`,
      "-enditem": (a, i, f) => `${a} 的 ${i} 没了` + (f ? `（${f}）` : ""), "-item": (a, i) => `${a} 的道具是 ${i}`,
      "-ability": (a, ab) => `${a} 的特性 ${ab} 发动`, "-status": (a, st) => `${a} 陷入${st}状态`, "-damage": (a, hp) => `${a} 剩余 ${hp}`,
      cant: (a, r) => `${a} 无法行动（${r}）`, win: w => `胜者：${w}`,
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
function from(f) {  // "[from] ability: Water Absorb" / "[from] move: Knock Off" / "[from] item: Air Balloon"
  if (!f) return "";
  const s = f.replace("[from] ", "");
  if (s.startsWith("ability: ")) return abilityName(s.slice(9));
  if (s.startsWith("move: ")) return moveName(s.slice(6));
  if (s.startsWith("item: ")) return itemName(s.slice(6));
  return s;
}
function event(line) {
  const f = line.split("|"), tag = f[0], E = L.ev;
  if (!E[tag]) return null;
  switch (tag) {
    case "move": return E.move(who(f[1]), moveName(f[2]), who(f[3]));
    case "-immune": return E[tag](who(f[1]), from(f[2]));
    case "-terastallize": return E[tag](who(f[1]), typeName(f[2]));
    case "-boost": case "-unboost": return E[tag](who(f[1]), ST[f[2]] || f[2], f[3]);
    case "-sidestart": case "-sideend": return E[tag](L.side(f[1].startsWith("ME")), moveName((f[2] || "").replace("move: ", "")));
    case "-enditem": return E[tag](who(f[1]), itemName(f[2]), from(f[3]));
    case "-item": return E[tag](who(f[1]), itemName(f[2]));
    case "-ability": return E[tag](who(f[1]), abilityName(f[2]));
    case "-status": return E[tag](who(f[1]), ST[f[2]] || f[2]);
    case "-damage": return /\d/.test(f[2] || "") ? E[tag](who(f[1]), f[2].split(" ")[0]) : null;
    case "cant": return E[tag](who(f[1]), from(f[2]) || f[2]);
    case "win": return E[tag](f[1]);
    default: return E[tag](who(f[1]), who(f[2]));
  }
}
function curve() {
  const s = document.getElementById("curve"), n = R.decisions.length, W = 600, H = 150, P = 8;
  if (!n) return;
  const x = i => P + (n == 1 ? 0 : i * (W - 2 * P) / (n - 1)), y = v => H - P - v * (H - 2 * P);
  let g = "";
  for (const v of [0, .5, 1]) g += `<line x1="${P}" x2="${W-P}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-dasharray="${v == .5 ? "4 4" : "1 0"}"/><text x="${W-P-2}" y="${y(v) - 3}" text-anchor="end" font-size="10" fill="var(--muted)">${100 * v}%</text>`;
  g += `<polyline fill="none" stroke="var(--me)" stroke-width="2" points="${R.decisions.map((d, i) => x(i) + "," + y(d.value)).join(" ")}"/>`;
  R.decisions.forEach((d, i) => {
    const bad = d.score >= 0.10;
    g += `<circle data-i="${i}" cx="${x(i)}" cy="${y(d.value)}" r="${i == cur ? 6 : bad ? 5 : 3}" fill="${bad ? "var(--bad)" : "var(--me)"}" stroke="${i == cur ? "var(--ink)" : "none"}" stroke-width="2"><title>${L.turn(d.turn)}: ${pct(d.value)}</title></circle>`;
  });
  s.innerHTML = g;
}
function decisionHTML(d) {
  const bad = d.score >= 0.10;
  let h = `<div class="dec"><h3>${L.turn(d.turn)}${L.kinds[d.kind] || ""} · ${L.now} ${pct(d.value)}<span class="tag ${bad ? "bad" : "ok"}">${bad ? L.bad : d.chosen == d.best ? L.same : L.ok}</span></h3>`;
  h += `<div class="legend">${L.bars}</div>`;
  const opts = d.options.slice();
  if (!opts.some(o => o[0] == d.chosen)) opts.push([d.chosen, d.chosen_share, d.chosen_value]);
  for (const [o, share, q] of opts) {
    const cls = o == d.chosen ? "me" : o == d.best ? "ai" : "";
    h += `<div class="opt"><span class="name ${cls}" title="${esc(o)}">${esc(option(o))}</span>
      <span class="bars"><span class="win" style="width:${q == null ? 0 : 100 * q}%"></span><span class="share" style="width:${100 * share}%"></span></span>
      <span class="num">${q == null ? L.untried : pct(q)}</span></div>`;
  }
  const st = d.state, me = st.me, op = st.opp;
  const b = x => Object.entries(x || {}).map(([k, v]) => (ST[k] || k) + " " + (v > 0 ? "+" + v : v)).join(", ");
  const sideText = (s, label) => `${label}: ${esc(monName(s.active.species))} ${pct(s.active.hp)}${Object.keys(s.boosts || {}).length ? " (" + b(s.boosts) + ")" : ""} · ${L.left(s.alive)}${s.tera_used ? " · " + L.tera : ""}`;
  h += `<div class="state">${sideText(me, L.you)} | ${sideText(op, L.opp)}${Object.keys(me.hazards).length ? " | " + L.hazMe + ": " + b(me.hazards) : ""}${Object.keys(op.hazards).length ? " | " + L.hazOpp + ": " + b(op.hazards) : ""}</div>`;
  const evs = (d.events || []).map(event).filter(Boolean);
  if (evs.length) h += `<div class="events"><b>${L.happened}</b>\n${evs.map(esc).join("\n")}</div>`;
  return h + "</div>";
}
function render() {
  const d = R.decisions[cur];
  const same = d ? R.decisions.filter(x => x.turn == d.turn) : [];
  document.getElementById("decisions").innerHTML = same.length ? same.map(decisionHTML).join("") : `<div class="none">${L.noDecision}</div>`;
  document.getElementById("moments").innerHTML = R.moments.map(m => `<li data-i="${m.i}">${L.moment(m.turn, esc(option(m.chosen)), esc(option(m.best)), pct(m.chosen_value), pct(m.best_value))}</li>`).join("") || `<li>${L.noMoments}</li>`;
  curve();
}
function battle() { return window.Replays && Replays.battle; }
function go(i, seek = true) {
  if (!R.decisions.length) return;
  cur = Math.max(0, Math.min(R.decisions.length - 1, i));
  render();
  const b = battle();
  if (seek && b) b.seekTurn(R.decisions[cur].turn);
}
document.title = L.title(R.id);
document.documentElement.lang = UI == "zh" ? "zh" : "en";
document.getElementById("title").textContent = L.title(R.id);
document.getElementById("res").textContent = R.won ? L.won : L.lost;
document.getElementById("note").textContent = L.note(R.ms, R.worlds);
document.getElementById("lui").textContent = L.ui;
document.getElementById("lnames").textContent = L.names;
document.getElementById("curvenote").textContent = L.curve;
document.getElementById("momentshead").textContent = L.momentsHead;
for (const k of ["first", "prev", "next", "mistake"]) document.querySelector(`[data-go="${k}"]`).textContent = L[k];
document.querySelectorAll(".lang button").forEach(btn => {
  if ((btn.dataset.k == "ui" ? UI : NAMES) == btn.dataset.v) btn.classList.add("sel");
  btn.addEventListener("click", () => setPref(btn.dataset.k, btn.dataset.v));
});
document.querySelector(".nav").addEventListener("click", e => {
  const a = e.target.dataset.go; if (!a) return;
  if (a == "first") go(0);
  if (a == "prev") go(cur - 1);
  if (a == "next") go(cur + 1);
  if (a == "mistake") {
    const j = R.decisions.findIndex((d, k) => k > cur && d.score >= 0.10);
    go(j >= 0 ? j : R.decisions.findIndex(d => d.score >= 0.10));
  }
});
document.getElementById("curve").addEventListener("click", e => { const i = e.target.dataset && e.target.dataset.i; if (i != null) go(+i); });
document.addEventListener("keydown", e => {
  if (e.key == "ArrowLeft") go(cur - 1);
  if (e.key == "ArrowRight") go(cur + 1);
  if (e.key == "m" || e.key == "M") document.querySelector('[data-go="mistake"]').click();
});
document.getElementById("moments").addEventListener("click", e => { const li = e.target.closest("li"); if (li && li.dataset.i != null) go(+li.dataset.i); });
render();
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
    if (state == "turn" || state == "paused" || state == "atqueueend") {
      const i = R.decisions.findIndex(d => d.turn == b.turn);
      if (i >= 0 && i != cur && R.decisions[cur].turn != b.turn) { cur = i; render(); }
    }
  });
  render();  // (the names, now that the client's data has loaded)
  const m = /t=(\d+)/.exec(location.hash);  // #t=<turn>: open at that turn's decision
  if (m) { const i = R.decisions.findIndex(d => d.turn == +m[1]); if (i >= 0) go(i); }
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
    ds = [d | {"score": round(mistake_score(d), 3), "events": events.get(d["turn"], [])}
          for d in report["decisions"]]  # fmt: skip
    index = {id(d): i for i, d in enumerate(report["decisions"])}
    moments = [{"i": index[id(m0)], **{k: m[k] for k in ("turn", "chosen", "best", "chosen_value", "best_value")}}
               for m in key_moments(report)
               for m0 in report["decisions"] if m0["turn"] == m["turn"] and m0["chosen"] == m["chosen"]
               and m0["kind"] == m["kind"]][:5]  # fmt: skip
    won = report["winner"] == report["side"]
    data = {"id": report["id"], "side": report["side"], "won": won, "turns": report["turns"],
            "ms": report["settings"]["ms"], "worlds": report["settings"]["worlds"],
            "decisions": ds, "moments": moments}  # fmt: skip
    log = row["log"].replace("</", "<\\/")
    return (PAGE.replace("__REVIEW__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__LOG__", log)
            .replace("__PLAYER__", LOCAL if client == "local" else OFFICIAL))  # fmt: skip
