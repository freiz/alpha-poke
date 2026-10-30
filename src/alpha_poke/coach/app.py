"""The review app (2026-10-29): the page server (coach.server) plus a home page where a player
pastes a replay link or picks a saved replay file, chooses which player they were and how deep
to look, and gets the review page when the search is done. Loopback only; one review at a time
(a background thread), progress polled by the page.

  GET  /                      the home page (the reviews so far, the form)
  POST /api/players           {source} or {upload: {name, text}} -> the replay's players
  POST /api/review            {source | upload, player, strength} -> {job}
  GET  /api/job/<id>          {status, done, total, url, error}
  GET  /api/reviews           the reviews in data/coach
"""

import json
import os
import queue
import re
import threading
import time
import uuid
from http import HTTPStatus
from pathlib import Path

from alpha_poke import paths
from alpha_poke.coach import narrate, replays, server, viewer
from alpha_poke.coach.review import review
from alpha_poke.selfplay.runner import MODEL

# search effort per decision: (belief worlds, milliseconds)
STRENGTH = {"fast": (8, 500), "standard": (16, 2000), "deep": (32, 5000)}
COACH = paths.DATA / "coach"
# the messages the page shows, in its interface language (the request's "lang")
MESSAGES = {
    "no_source": {"en": "Paste a replay link or id, or pick a replay file.",
                  "zh": "请粘贴回放链接或编号，或者选择一个回放文件。"},
    "not_a_link": {"en": "Paste a Showdown replay link or id.", "zh": "请粘贴 Showdown 回放链接或编号。"},
    "format": {"en": "Only Gen 9 OU games can be reviewed (this one: {fmt}).",
               "zh": "只支持 Gen 9 OU 的对局（这一局：{fmt}）。"},
    "player": {"en": "Choose which player you were.", "zh": "请选择你是哪一位玩家。"},
}  # fmt: skip


class Refused(ValueError):
    """A request the page explains (MESSAGES key)."""


def message(key: str, lang: str, **kw) -> str:
    return MESSAGES[key]["zh" if lang == "zh" else "en"].format(**kw)


UPLOADS = COACH / "uploads"


def model_dir() -> str:
    """The network (the released one) under the data directory (ALPHA_DATA in the app)."""
    return str(paths.DATA / Path(MODEL).relative_to("data"))


class Jobs:
    """The reviews asked for, run one at a time on a background thread."""

    def __init__(self, threads: int, model: str | None = None, strengths: dict | None = None):
        self.threads, self.model, self.strengths = threads, model, strengths or STRENGTH
        self.jobs: dict[str, dict] = {}
        self.queue: queue.Queue = queue.Queue()
        self._belief = None
        threading.Thread(target=self._work, daemon=True).start()

    def belief(self):
        if self._belief is None:
            from alpha_poke.agents.belief_state import BeliefModel

            self._belief = BeliefModel.load()
        return self._belief

    def submit(self, row: dict, player: str, strength: str) -> str:
        jid = uuid.uuid4().hex[:12]
        self.jobs[jid] = {"status": "queued", "done": 0, "total": 0, "url": None, "error": None}
        self.queue.put((jid, row, player, strength))
        return jid

    def _work(self) -> None:
        while True:
            jid, row, player, strength = self.queue.get()
            job = self.jobs[jid]
            try:
                job["status"] = "running"
                side = replays.side_of(row, player)
                worlds, ms = self.strengths.get(strength, self.strengths["standard"])

                def progress(done, total, job=job):
                    job["done"], job["total"] = done, total

                rep = review(row, side, self.belief(), self.model or model_dir(), worlds=worlds, ms=ms,
                             threads=self.threads, log=lambda *_: None, progress=progress)  # fmt: skip
                out = COACH / f"{row['id']}-{side}"
                out.mkdir(parents=True, exist_ok=True)
                (out / "review.json").write_text(
                    json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8"
                )
                (out / "summary.md").write_text(narrate.summary(rep), encoding="utf-8")
                (out / "viewer.html").write_text(
                    viewer.render(rep, row, client="local"), encoding="utf-8"
                )
                job["url"] = f"/coach/{out.name}/viewer.html"
                job["status"] = "done"
            except Exception as e:  # noqa: BLE001 - shown on the page
                job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"


def load_row(body: dict) -> dict:
    """The replay of a request: {"source": a link / id} or {"upload": {"name", "text"}}."""
    up = body.get("upload")
    if up:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(up.get("name") or "replay.html").name)[-80:]
        UPLOADS.mkdir(parents=True, exist_ok=True)
        path = UPLOADS / name
        path.write_text(up.get("text") or "", encoding="utf-8")
        return replays.load(str(path))
    source = (body.get("source") or "").strip()
    if not source:
        raise Refused("no_source")
    if Path(source).exists():  # (only links and ids from the page: no local paths)
        raise Refused("not_a_link")
    return replays.load(source)


def reviews() -> list[dict]:
    out = []
    for f in sorted(COACH.glob("*/review.json"), key=lambda p: -p.stat().st_mtime):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"url": f"/coach/{f.parent.name}/viewer.html", "id": r["id"], "player": r.get("player"),
                    "won": r["winner"] == r["side"], "turns": r["turns"],
                    "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))})  # fmt: skip
    return out


def handler(cache, jobs: Jobs):
    base = server.handler(cache, COACH)

    class Handler(base):
        def _json(self, obj, status=HTTPStatus.OK) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(HOME.encode(), "text/html; charset=utf-8")
            if path == "/api/reviews":
                return self._json(reviews())
            m = re.fullmatch(r"/api/job/([0-9a-f]+)", path)
            if m:
                job = jobs.jobs.get(m.group(1))
                return (
                    self._json(job)
                    if job
                    else self._json({"error": "no such job"}, HTTPStatus.NOT_FOUND)
                )
            return super().do_GET()

        def do_POST(self):  # noqa: N802
            # (only our own page may ask: another site's page in the same browser cannot)
            origin = self.headers.get("Origin")
            if origin and origin.split("//", 1)[-1] != self.headers.get("Host"):
                return self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            n = int(self.headers.get("Content-Length") or 0)
            lang = "en"
            try:
                body = json.loads(self.rfile.read(min(n, 20_000_000)) or b"{}")
                lang = body.get("lang") or "en"
                row = load_row(body)
            except Refused as e:
                return self._json({"error": message(str(e), lang)}, HTTPStatus.BAD_REQUEST)
            except Exception as e:  # noqa: BLE001 - the page shows it
                return self._json({"error": str(e) or type(e).__name__}, HTTPStatus.BAD_REQUEST)
            if not row.get("formatid", "").startswith("gen9ou"):
                return self._json({"error": message("format", lang, fmt=row.get("formatid"))},
                                  HTTPStatus.BAD_REQUEST)  # fmt: skip
            if self.path == "/api/players":
                return self._json({"id": row["id"], "players": row["players"]})
            if self.path == "/api/review":
                player = body.get("player") or ""
                if player not in row["players"]:
                    return self._json({"error": message("player", lang)}, HTTPStatus.BAD_REQUEST)
                return self._json(
                    {"job": jobs.submit(row, player, body.get("strength") or "standard")}
                )
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def make(port: int, offline: bool = False, refresh: bool = False, threads: int | None = None,
         model: str | None = None, strengths: dict | None = None, host: str = "127.0.0.1"):  # fmt: skip
    """The app's server on ``host``:``port`` (``serve_forever()`` it): loopback by default;
    "0.0.0.0" opens it to the local network (the family's other devices; anyone on the network
    can then start reviews)."""
    from http.server import ThreadingHTTPServer

    cache = server.Cache(COACH / "client", offline, refresh)
    jobs = Jobs(threads or max(1, min(4, (os.cpu_count() or 2) - 1)), model, strengths)
    return ThreadingHTTPServer((host, port), handler(cache, jobs))


def free_port(start: int = 8090) -> int:
    """The first port from ``start`` nobody listens on (our app already on one: that one)."""
    import socket

    for port in range(start, start + 50):
        if server.running(port):
            return port
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port")


HOME = r"""<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Game review</title>
<style>
  :root { --bg: #f5f6f8; --panel: #fff; --ink: #1d2330; --muted: #677085; --line: #d9dde5; --ai: #3567d6; --bad: #d64545; --good: #2f9e5b; }
  @media (prefers-color-scheme: dark) { :root { --bg: #15181e; --panel: #1f242d; --ink: #e6e9ef; --muted: #9aa3b5; --line: #343b48; } }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 24px 16px; }
  .top { display: flex; align-items: baseline; gap: 12px; } .top .lang { margin-left: auto; font-size: 12px; color: var(--muted); }
  .lang button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); padding: 2px 8px; cursor: pointer; font: inherit; margin: 0; border-radius: 0; }
  .lang button.sel { background: var(--ai); color: #fff; border-color: var(--ai); }
  h1 { font-size: 22px; margin: 0 0 4px; } .muted { color: var(--muted); font-size: 13px; }
  section { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin: 16px 0; }
  label { display: block; margin: 10px 0 4px; font-weight: 600; }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--ink); font: inherit; }
  .go { background: var(--ai); color: #fff; border: 0; border-radius: 6px; padding: 8px 16px; font: inherit; cursor: pointer; margin-top: 12px; }
  .go:disabled { opacity: .5; cursor: default; }
  .choice { display: flex; gap: 14px; flex-wrap: wrap; } .choice label { font-weight: 400; margin: 4px 0; }
  .err { color: var(--bad); margin-top: 8px; } .bar { height: 10px; background: var(--bg); border-radius: 5px; overflow: hidden; margin-top: 10px; }
  .bar span { display: block; height: 100%; background: var(--ai); width: 0; transition: width .3s; }
  ul { padding-left: 18px; } li { margin: 4px 0; } a { color: var(--ai); }
  .won { color: var(--good); } .lost { color: var(--bad); }
</style>
<main>
  <div class="top"><h1 data-t="title"></h1>
    <span class="lang"><span data-t="ui"></span> <button data-v="en">EN</button><button data-v="zh">中文</button></span></div>
  <div class="muted" data-t="intro"></div>
  <section>
    <label for="src" data-t="link"></label>
    <input type="text" id="src" placeholder="https://replay.pokemonshowdown.com/gen9ou-1234567890" />
    <label for="file" data-t="fileLabel"></label>
    <input type="file" id="file" accept=".html,.json,.log,.txt" />
    <div><button class="go" id="load" data-t="load"></button></div>
    <div id="pick" hidden>
      <label data-t="which"></label><div class="choice" id="players"></div>
      <label data-t="strength"></label>
      <div class="choice">
        <label><input type="radio" name="strength" value="fast" /> <span data-t="fast"></span></label>
        <label><input type="radio" name="strength" value="standard" checked /> <span data-t="standard"></span></label>
        <label><input type="radio" name="strength" value="deep" /> <span data-t="deep"></span></label>
      </div>
      <button class="go" id="go" data-t="start"></button>
    </div>
    <div id="progress" hidden><div class="muted" id="ptext"></div><div class="bar"><span id="pbar"></span></div></div>
    <div class="err" id="err"></div>
  </section>
  <section><b data-t="past"></b><ul id="list"></ul></section>
</main>
<script>
const T = {
  en: {title: "Game review", ui: "Interface",
       intro: "An AI rethinks each of your decisions from your side of the game: every option's winning chance, the AI's choice, the key mistakes. Gen 9 OU only. Everything runs on your computer.",
       link: "Showdown replay link or id", fileLabel: "or a saved replay file (.html / .json / .log)", load: "Load the game",
       which: "Which player were you?", strength: "How deep to look", fast: "Fast (about half a minute)",
       standard: "Standard (1–2 minutes)", deep: "Deep (about 5 minutes)", start: "Review", past: "Reviews so far", none: "None yet.",
       queued: "Waiting…", building: "Rebuilding each decision's position…", step: (d, n) => `Thinking about decision ${d} of ${n}…`,
       won: "won", lost: "lost", turns: n => `${n} turns`},
  zh: {title: "对局复盘", ui: "界面",
       intro: "AI 从你的视角重新思考你的每一步：每个选择的胜率、AI 的选择、关键失误。只支持 Gen 9 OU。全部在你的电脑上运行。",
       link: "Showdown 回放链接或编号", fileLabel: "或者选择保存的回放文件（.html / .json / .log）", load: "读取对局",
       which: "你是哪一位玩家？", strength: "分析强度", fast: "快速（约半分钟）", standard: "标准（1–2 分钟）",
       deep: "深入（约 5 分钟）", start: "开始分析", past: "以前的复盘", none: "还没有。",
       queued: "排队中……", building: "正在重建每一步的局面……", step: (d, n) => `正在分析第 ${d} / ${n} 步……`,
       won: "胜", lost: "负", turns: n => `${n} 回合`},
};
let UI = "en";
try { UI = new URLSearchParams(location.search).get("ui") || localStorage.getItem("coach-ui") || "en"; } catch (e) {}
if (UI != "zh") UI = "en";
const L = T[UI];
document.documentElement.lang = UI; document.title = L.title;
document.querySelectorAll("[data-t]").forEach(el => { el.textContent = L[el.dataset.t]; });
document.querySelectorAll(".lang button").forEach(b => {
  if (b.dataset.v == UI) b.classList.add("sel");
  b.onclick = () => { try { localStorage.setItem("coach-ui", b.dataset.v); } catch (e) {} location.search = "?ui=" + b.dataset.v; };
});
const $ = id => document.getElementById(id);
const esc = x => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
let body = null;
async function post(url, data) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({...data, lang: UI})});
  const j = await r.json(); if (!r.ok) throw new Error(j.error || r.statusText); return j;
}
async function source() {
  const f = $("file").files[0];
  if (f) return {upload: {name: f.name, text: await f.text()}};
  return {source: $("src").value};
}
$("load").onclick = async () => {
  $("err").textContent = ""; $("pick").hidden = true;
  try {
    body = await source();
    const r = await post("/api/players", body);
    $("players").innerHTML = r.players.filter(Boolean).map((p, i) =>
      `<label><input type="radio" name="player" value="${esc(p)}" ${i ? "" : "checked"} /> ${esc(p)}</label>`).join("");
    $("pick").hidden = false;
  } catch (e) { $("err").textContent = e.message; }
};
$("go").onclick = async () => {
  $("err").textContent = ""; $("go").disabled = true; $("progress").hidden = false; $("ptext").textContent = L.queued;
  try {
    const player = document.querySelector("input[name=player]:checked").value;
    const strength = document.querySelector("input[name=strength]:checked").value;
    const {job} = await post("/api/review", {...body, player, strength});
    const poll = async () => {
      const j = await (await fetch("/api/job/" + job)).json();
      if (j.status == "error") throw new Error(j.error);
      if (j.total) { $("ptext").textContent = L.step(j.done, j.total); $("pbar").style.width = (100 * j.done / j.total) + "%"; }
      else $("ptext").textContent = j.status == "queued" ? L.queued : L.building;
      if (j.status == "done") { location.href = j.url; return; }
      setTimeout(() => poll().catch(e => { $("err").textContent = e.message; $("go").disabled = false; }), 1000);
    };
    await poll();
  } catch (e) { $("err").textContent = e.message; $("go").disabled = false; }
};
fetch("/api/reviews").then(r => r.json()).then(list => {
  $("list").innerHTML = list.length ? list.map(r =>
    `<li><a href="${r.url}">${esc(r.id)}</a> · ${esc(r.player || "")} · <span class="${r.won ? "won" : "lost"}">${r.won ? L.won : L.lost}</span> · ${L.turns(r.turns)} · <span class="muted">${r.date}</span></li>`).join("")
    : `<li class="muted">${L.none}</li>`;
});
</script>
</html>
"""
