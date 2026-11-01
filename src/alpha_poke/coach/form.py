"""The review settings form, one for the home page (a new review) and the review page (the same
game again, deeper): how deep to look (the presets or custom searches x seconds x worlds), the
player's own team (an export or a PokéPaste link), searches at once, the decision count and the
estimated time, the start button and the progress. CSS scoped to ``.rf``; the script defines
``reviewForm(ui, info, opts)``:

  info  {strengths: {name: [worlds, ms, repeats]}, max_parallel, threads} (the app's)
  opts  {decisions(): the count, submit(values) -> job id, done(url), preset, custom: [worlds,
         seconds, repeats], keptTeam: a team from before is kept when the box is left empty (or
         a function saying so: checked again with each estimate)}
"""

CSS = r"""
  .rf label { display: block; margin: 10px 0 4px; font-weight: 600; }
  .rf .choice { display: flex; gap: 14px; flex-wrap: wrap; } .rf .choice label { font-weight: 400; margin: 4px 0; }
  .rf .muted { color: var(--muted); font-size: 13px; }
  .rf textarea { width: 100%; box-sizing: border-box; min-height: 7em; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px;
                 background: var(--bg); color: var(--ink); font: 13px/1.4 ui-monospace, monospace; }
  .rf input[type=number] { background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 4px; padding: 2px 4px; font: inherit; }
  .rf .est { margin-top: 10px; }
  .rf .go { background: var(--ai); color: #fff; border: 0; border-radius: 6px; padding: 8px 16px; font: inherit; cursor: pointer; margin-top: 12px; }
  .rf .go:disabled { opacity: .5; cursor: default; }
  .rf .err { color: var(--bad); margin-top: 8px; }
  .rf .pbar { height: 10px; background: var(--bg); border-radius: 5px; overflow: hidden; margin-top: 10px; }
  .rf .pbar span { display: block; height: 100%; background: var(--ai); width: 0; transition: width .3s; }
"""

HTML = r"""<div class="rf">
  <label data-rf="strength"></label>
  <div class="choice">
    <label><input type="radio" name="rf-strength" value="fast" /> <span data-rf="fast"></span></label>
    <label><input type="radio" name="rf-strength" value="standard" checked /> <span data-rf="standard"></span></label>
    <label><input type="radio" name="rf-strength" value="deep" /> <span data-rf="deep"></span></label>
    <label><input type="radio" name="rf-strength" value="custom" /> <span data-rf="custom"></span></label>
  </div>
  <div class="choice" id="rf-customize" hidden>
    <label><span data-rf="repeats"></span> <input type="number" id="rf-repeats" min="1" max="8" value="3" style="width:4em" /></label>
    <label><span data-rf="seconds"></span> <input type="number" id="rf-seconds" min="0.2" max="10" step="0.1" value="2" style="width:4.5em" /></label>
    <label><span data-rf="worlds"></span> <input type="number" id="rf-worlds" min="4" max="64" value="16" style="width:4em" /></label>
  </div>
  <div class="muted" data-rf="strengthNote"></div>
  <label for="rf-team" data-rf="teamLabel"></label>
  <textarea id="rf-team" spellcheck="false" placeholder="https://pokepast.es/…"></textarea>
  <div class="muted" id="rf-teamnote"></div>
  <label><span data-rf="parallel"></span> <input type="number" id="rf-parallel" min="1" value="2" style="width:4em" /></label>
  <div class="muted" id="rf-parallelnote"></div>
  <div class="est" id="rf-est"></div>
  <button class="go" id="rf-go" data-rf="start"></button>
  <div id="rf-progress" hidden><div class="muted" id="rf-ptext"></div><div class="pbar"><span id="rf-pbar"></span></div></div>
  <div class="err" id="rf-err"></div>
</div>"""

JS = r"""
const RF_T = {
  en: {strength: "How deep to look", fast: "Fast: 1 search × 0.5 s per decision", standard: "Standard: 3 searches × 2 s",
       deep: "Deep: 5 searches × 3 s", custom: "Custom", repeats: "searches", seconds: "seconds each", worlds: "belief worlds",
       strengthNote: "More searches give steadier numbers and their error ranges (everything hidden is guessed anew each time).",
       teamLabel: "Your team (optional, recommended)",
       teamNote: "Paste the team you played (Showdown teambuilder → Export) or its PokéPaste link. With it the engine knows your sets exactly, as you did. Without it, the moves, items and spreads the game did not show are guesses: the engine may suggest a move you do not have (marked “guess”), and the error ranges grow.",
       kept: "Left empty: the team pasted last time is used.",
       parallel: "Searches at once", parallelNote: (t, m) => `Each search uses ${t} threads; this computer has room for ${m} at once. More is faster.`,
       est: (n, t) => `<b>${n}</b> decisions to review · about <b>${t}</b>`, min: m => `${m} min`, sec: s => `${s} s`,
       start: "Review", queued: "Waiting…", building: "Rebuilding each decision's position…", step: (d, n) => `Decisions reviewed: ${d} of ${n}…`},
  zh: {strength: "分析强度", fast: "快速：每步 1 次搜索 × 0.5 秒", standard: "标准：3 次 × 2 秒", deep: "深入：5 次 × 3 秒", custom: "自定义",
       repeats: "搜索次数", seconds: "每次秒数", worlds: "信念世界数",
       strengthNote: "搜索次数越多，数字越稳，还能给出误差范围（每次都把看不到的部分重新猜一遍）。",
       teamLabel: "你的队伍（可选，建议贴上）",
       teamNote: "粘贴你这局用的队伍（Showdown 队伍编辑器 → Export 导出），或者它的 PokéPaste 链接。贴上后引擎和你一样清楚自己的配置。不贴的话，这局没亮出来的招式、道具、努力值都只能靠猜：引擎可能推荐你根本没带的招式（会标“推测”），误差范围也会变大。",
       kept: "留空就沿用上次粘贴的队伍。",
       parallel: "同时进行的搜索数", parallelNote: (t, m) => `每个搜索用 ${t} 个线程；这台电脑最多可以同时跑 ${m} 个。越多越快。`,
       est: (n, t) => `共 <b>${n}</b> 步决策 · 预计约 <b>${t}</b>`, min: m => `${m} 分钟`, sec: s => `${s} 秒`,
       start: "开始分析", queued: "排队中……", building: "正在重建每一步的局面……", step: (d, n) => `已分析 ${d} / ${n} 步……`},
};
function reviewForm(ui, info, opts) {
  const L = RF_T[ui == "zh" ? "zh" : "en"], $ = id => document.getElementById(id);
  document.querySelectorAll("[data-rf]").forEach(el => { el.textContent = L[el.dataset.rf]; });
  const radios = [...document.querySelectorAll("input[name=rf-strength]")];
  const chosen = () => (radios.find(r => r.checked) || {}).value || "standard";
  if (opts.preset) radios.forEach(r => { r.checked = r.value == opts.preset; });
  if (opts.custom) [["rf-worlds", 0], ["rf-seconds", 1], ["rf-repeats", 2]].forEach(([id, k]) => { $(id).value = opts.custom[k]; });
  $("rf-customize").hidden = chosen() != "custom";
  $("rf-parallel").max = info.max_parallel; $("rf-parallel").value = Math.min(2, info.max_parallel);
  $("rf-parallelnote").textContent = L.parallelNote(info.threads, info.max_parallel);
  function effort() {  // [worlds, seconds, searches] of the chosen strength
    const s = chosen();
    if (s == "custom") return [+$("rf-worlds").value, +$("rf-seconds").value, +$("rf-repeats").value];
    const [w, ms, r] = info.strengths[s] || info.strengths.standard; return [w, ms / 1000, r];
  }
  function estimate() {  // the searches in waves of `parallel`, plus rebuilding the positions (≈ 4.5 ms per world)
    const kept = typeof opts.keptTeam == "function" ? opts.keptTeam() : opts.keptTeam;
    $("rf-teamnote").textContent = L.teamNote + (kept ? " " + L.kept : "");
    const n = opts.decisions() || 0, [w, s, r] = effort();
    const p = Math.min(Math.max(1, +$("rf-parallel").value || 1), info.max_parallel);
    const secs = Math.ceil(n * r / p) * s + r * n * w * 0.0045;
    $("rf-est").innerHTML = L.est(n, secs >= 90 ? L.min(Math.round(secs / 60)) : L.sec(Math.max(1, Math.round(secs))));
  }
  // (properties, not listeners: a form set up again -- another game loaded -- has one handler each)
  radios.forEach(r => { r.onchange = () => { $("rf-customize").hidden = chosen() != "custom"; estimate(); }; });
  ["rf-repeats", "rf-seconds", "rf-worlds", "rf-parallel"].forEach(id => { $(id).oninput = estimate; });
  $("rf-go").onclick = async () => {
    $("rf-err").textContent = ""; $("rf-go").disabled = true; $("rf-progress").hidden = false; $("rf-ptext").textContent = L.queued;
    const fail = e => { $("rf-err").textContent = e.message; $("rf-go").disabled = false; };
    try {
      const s = chosen(), [worlds, seconds, repeats] = effort();
      const job = await opts.submit({strength: s, custom: s == "custom" ? {repeats, seconds, worlds} : null,
                                     team: $("rf-team").value, parallel: +$("rf-parallel").value});
      const poll = async () => {
        const j = await (await fetch("/api/job/" + job)).json();
        if (j.status == "error") throw new Error(j.error);
        if (j.total) { $("rf-ptext").textContent = L.step(j.done, j.total); $("rf-pbar").style.width = (100 * j.done / j.total) + "%"; }
        else $("rf-ptext").textContent = j.status == "queued" ? L.queued : L.building;
        if (j.status == "done") return opts.done(j.url);
        setTimeout(() => poll().catch(fail), 1000);
      };
      await poll();
    } catch (e) { fail(e); }
  };
  estimate();
  return {estimate};
}
"""


def embed(page: str) -> str:
    """``page`` with the form's parts in place of __RF_CSS__ / __RF_HTML__ / __RF_JS__."""
    return page.replace("__RF_CSS__", CSS).replace("__RF_HTML__", HTML).replace("__RF_JS__", JS)
