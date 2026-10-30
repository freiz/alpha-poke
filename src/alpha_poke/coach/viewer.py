"""A game review as one HTML page (2026-10-29): Showdown's own replay player (sprites,
animations: its replay-embed.js, MIT, loaded from play.pokemonshowdown.com -- the client's look
and data stay current without us) next to the review: the winning-chance curve with the
mistakes marked, each decision's options (the search's winning chance and share of visits), the
player's choice and the search's; previous / next decision, next mistake, the keyboard; the
player and the panel follow each other (Battle.seekTurn / subscribe). Open it in a browser (a
local file: it needs the internet for the player's scripts and sprites)."""

import html
import json

from alpha_poke.coach.review import key_moments, mistake_score, turn_events

PAGE = r"""<!DOCTYPE html>
<html lang="zh">
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
</style>
<header>
  <h1>复盘 · __ID__</h1><span class="res">__RESULT__</span>
  <span class="legend">分析视角：__ME__ ｜ 胜率为 AI 搜索的估计（每步 __MS__ ms × __WORLDS__ 个信念世界）</span>
</header>
<main>
  <div class="wrapper replay-wrapper">
    <div class="battle"></div><div class="battle-log"></div>
    <div class="replay-controls"></div><div class="replay-controls-2"></div>
  </div>
  <section id="panel">
    <svg id="curve" viewBox="0 0 600 150" preserveAspectRatio="none" aria-label="胜率曲线"></svg>
    <div class="legend">胜率曲线（橙点：你的决策；红点：AI 明显不同意的决策）。点击曲线跳到该回合。←/→ 上一步 / 下一步，M 下一个失误。</div>
    <div class="nav">
      <button data-go="first">⏮ 开局</button><button data-go="prev">◀ 上一步</button>
      <button data-go="next">下一步 ▶</button><button data-go="mistake">⚠ 下一个失误</button>
    </div>
    <div id="decisions"></div>
    <h3>AI 最不认同的决策</h3><ol class="moments" id="moments"></ol>
  </section>
</main>
<script type="text/plain" class="battle-log-data">__LOG__</script>
<script>
const R = __REVIEW__;
const SIDE = R.side;
let cur = 0;  // index into R.decisions
const pct = v => v == null ? "—" : Math.round(100 * v) + "%";
function pretty(o) {
  const dex = window.BattleMovedex || {}, mons = window.BattlePokedex || {};
  if (o.startsWith("switch ")) { const id = o.slice(7); return "换上 " + ((mons[id] && mons[id].name) || id); }
  const tera = o.endsWith("-tera"), id = tera ? o.slice(0, -5) : o;
  return ((dex[id] && dex[id].name) || id) + (tera ? " + 太晶" : "");
}
function mon(id) { const m = (window.BattlePokedex || {})[String(id).toLowerCase()]; return (m && m.name) || id; }
const EV = {
  "move": (a, m, t) => `${a} 使用了 ${m}` + (t ? `（对 ${t}）` : ""), "switch": a => `${a} 上场`, "drag": a => `${a} 被强制换上场`,
  "faint": a => `${a} 倒下了`, "-supereffective": a => `→ 对 ${a} 效果绝佳`, "-resisted": a => `→ ${a} 抵抗了（效果不好）`,
  "-immune": (a, f) => `→ ${a} 免疫` + (f ? `（${f.replace("[from] ", "")}）` : ""), "-crit": a => `→ 击中要害（暴击）`,
  "-miss": (a, t) => `${a} 的招式没有命中`, "-terastallize": (a, t) => `${a} 太晶化为 ${t} 属性`,
  "-boost": (a, s, n) => `${a} 的 ${s} 提升 ${n} 级`, "-unboost": (a, s, n) => `${a} 的 ${s} 下降 ${n} 级`,
  "-sidestart": (a, c) => `${a.startsWith("你") ? "你" : "对手"}这一侧被放了 ${c.replace("move: ", "")}`, "-sideend": (a, c) => `${a.startsWith("你") ? "你" : "对手"}这一侧的 ${c.replace("move: ", "")} 被清除`, "-enditem": (a, i, f) => `${a} 的 ${i} 没了` + (f ? `（${f.replace("[from] ", "")}）` : ""),
  "-item": (a, i) => `${a} 的道具是 ${i}`, "-ability": (a, ab) => `${a} 的特性 ${ab} 发动`, "-status": (a, st) => `${a} 陷入异常状态 ${st}`,
  "-damage": (a, hp) => `${a} 剩余 ${hp.split(" ")[0]}`, "cant": (a, r) => `${a} 无法行动（${r}）`, "win": a => `胜者：${a}`,
};
function event(line) {
  const f = line.split("|"), tag = f[0];
  const who = x => (x || "").replace(/^ME /, "你的 ").replace(/^OPP /, "对手的 ");
  if (!EV[tag]) return null;
  if (tag == "-damage" && !/\d/.test(f[2] || "")) return null;
  return EV[tag](who(f[1]), who(f[2]), who(f[3]));
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
    g += `<circle data-i="${i}" cx="${x(i)}" cy="${y(d.value)}" r="${i == cur ? 6 : bad ? 5 : 3}" fill="${bad ? "var(--bad)" : "var(--me)"}" stroke="${i == cur ? "var(--ink)" : "none"}" stroke-width="2"><title>回合 ${d.turn}：${pct(d.value)}</title></circle>`;
  });
  s.innerHTML = g;
}
function decisionHTML(d) {
  const bad = d.score >= 0.10;
  let h = `<div class="dec"><h3>回合 ${d.turn}${d.kind != "turn" ? "（" + (d.kind == "pivot switch" ? "折返换人" : "倒下后换人") + "）" : ""}
    · 当前胜率 ${pct(d.value)}<span class="tag ${bad ? "bad" : "ok"}">${bad ? "AI 不认同" : d.chosen == d.best ? "和 AI 一致" : "可以接受"}</span></h3>`;
  h += `<div class="legend">长条：选这一步后的胜率；底部细条：AI 搜索在这一步上花的比例。<span style="color:var(--me)">橙色</span>=你的选择，<span style="color:var(--ai)">蓝色</span>=AI 的选择</div>`;
  const opts = d.options.slice();
  if (!opts.some(o => o[0] == d.chosen)) opts.push([d.chosen, d.chosen_share, d.chosen_value]);
  for (const [o, share, q] of opts) {
    const cls = o == d.chosen ? "me" : o == d.best ? "ai" : "";
    h += `<div class="opt"><span class="name ${cls}" title="${o}">${pretty(o)}</span>
      <span class="bars"><span class="win" style="width:${q == null ? 0 : 100 * q}%"></span><span class="share" style="width:${100 * share}%"></span></span>
      <span class="num">${q == null ? "未尝试" : pct(q)}</span></div>`;
  }
  const st = d.state, me = st.me, op = st.opp, b = x => Object.entries(x || {}).map(([k, v]) => k.replace("_", " ") + " " + (v > 0 ? "+" + v : v)).join(", ");
  h += `<div class="state">你：${mon(me.active.species)} ${pct(me.active.hp)}${me.boosts && Object.keys(me.boosts).length ? "（" + b(me.boosts) + "）" : ""} · 剩 ${me.alive} 只${me.tera_used ? " · 已太晶" : ""}
    ｜ 对手：${mon(op.active.species)} ${pct(op.active.hp)}${op.boosts && Object.keys(op.boosts).length ? "（" + b(op.boosts) + "）" : ""} · 剩 ${op.alive} 只${op.tera_used ? " · 已太晶" : ""}
    ${Object.keys(me.hazards).length ? " ｜ 你这边的钉子：" + b(me.hazards) : ""}${Object.keys(op.hazards).length ? " ｜ 对手那边的钉子：" + b(op.hazards) : ""}</div>`;
  const evs = (d.events || []).map(event).filter(Boolean);
  if (evs.length) h += `<div class="events"><b>这一回合发生了什么：</b>\n${evs.map(e => e.replace(/&/g, "&amp;").replace(/</g, "&lt;")).join("\n")}</div>`;
  return h + "</div>";
}
function render() {
  const d = R.decisions[cur];
  const same = d ? R.decisions.filter(x => x.turn == d.turn) : [];
  document.getElementById("decisions").innerHTML = same.length ? same.map(decisionHTML).join("") : `<div class="none">这一回合你没有需要做的决策。</div>`;
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
document.getElementById("moments").innerHTML = R.moments.map(m => `<li data-i="${m.i}">回合 ${m.turn}：你选了 <b>${m.chosen}</b>，AI 选 <b>${m.best}</b>（${pct(m.chosen_value)} → ${pct(m.best_value)}）</li>`).join("") || "<li>没有明显的失误。</li>";
document.getElementById("moments").addEventListener("click", e => { const li = e.target.closest("li"); if (li && li.dataset.i != null) go(+li.dataset.i); });
render();
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
  render();  // (the move names, now that the client's data has loaded)
  const m = /t=(\d+)/.exec(location.hash);  // #t=<turn>: open at that turn's decision
  if (m) { const i = R.decisions.findIndex(d => d.turn == +m[1]); if (i >= 0) go(i); }
}, 200);
</script>
__PLAYER__
</html>
"""

# official: Showdown's replay-embed.js from its site (works from a local file)
OFFICIAL = '<script src="https://play.pokemonshowdown.com/js/replay-embed.js"></script>'

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
    var p = this.battle.paused;
    $('.replay-controls').html('<button data-action="' + (p ? 'play' : 'pause') + '"><i class="fa fa-' + (p ? 'play' : 'pause') + '"></i> '
      + (p ? 'Play' : 'Pause') + '</button><button data-action="reset"><i class="fa fa-undo"></i> Reset</button> '
      + '<button data-action="rewind"><i class="fa fa-step-backward"></i> Last turn</button><button data-action="ff">'
      + '<i class="fa fa-step-forward"></i> Next turn</button>');
  }
};
window.addEventListener('load', function () { Replays.init(); });
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
    data = {"side": report["side"], "decisions": ds, "moments": moments}
    won = report["winner"] == report["side"]
    log = row["log"].replace("</", "<\\/")
    return (PAGE.replace("__REVIEW__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__LOG__", log)
            .replace("__ID__", html.escape(report["id"]))
            .replace("__RESULT__", "胜" if won else "负")
            .replace("__ME__", "p1（左下）" if report["side"] == "p1" else "p2")
            .replace("__MS__", str(report["settings"]["ms"]))
            .replace("__WORLDS__", str(report["settings"]["worlds"]))
            .replace("__PLAYER__", LOCAL if client == "local" else OFFICIAL))  # fmt: skip
