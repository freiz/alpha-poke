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
                (out / "review.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
                (out / "summary.md").write_text(narrate.summary(rep))
                (out / "viewer.html").write_text(viewer.render(rep, row, client="local"))
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
        path.write_text(up.get("text") or "")
        return replays.load(str(path))
    source = (body.get("source") or "").strip()
    if not source:
        raise ValueError("请粘贴回放链接或编号，或者选择一个回放文件")
    if Path(source).exists():  # (only links and ids from the page: no local paths)
        raise ValueError("请粘贴 Showdown 回放链接或编号")
    return replays.load(source)


def reviews() -> list[dict]:
    out = []
    for f in sorted(COACH.glob("*/review.json"), key=lambda p: -p.stat().st_mtime):
        try:
            r = json.loads(f.read_text())
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
            try:
                body = json.loads(self.rfile.read(min(n, 20_000_000)) or b"{}")
                row = load_row(body)
            except Exception as e:  # noqa: BLE001 - the page shows it
                return self._json({"error": str(e) or type(e).__name__}, HTTPStatus.BAD_REQUEST)
            if not row.get("formatid", "").startswith("gen9ou"):
                return self._json({"error": f"只支持 Gen 9 OU 的对局（这一局：{row.get('formatid')}）"},
                                  HTTPStatus.BAD_REQUEST)  # fmt: skip
            if self.path == "/api/players":
                return self._json({"id": row["id"], "players": row["players"]})
            if self.path == "/api/review":
                player = body.get("player") or ""
                if player not in row["players"]:
                    return self._json({"error": "请选择你是哪一位玩家"}, HTTPStatus.BAD_REQUEST)
                return self._json(
                    {"job": jobs.submit(row, player, body.get("strength") or "standard")}
                )
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def make(port: int, offline: bool = False, refresh: bool = False, threads: int | None = None,
         model: str | None = None, strengths: dict | None = None):  # fmt: skip
    """The app's server on 127.0.0.1:``port`` (``serve_forever()`` it)."""
    from http.server import ThreadingHTTPServer

    cache = server.Cache(COACH / "client", offline, refresh)
    jobs = Jobs(threads or max(1, min(4, (os.cpu_count() or 2) - 1)), model, strengths)
    return ThreadingHTTPServer(("127.0.0.1", port), handler(cache, jobs))


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
<html lang="zh">
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>对局复盘</title>
<style>
  :root { --bg: #f5f6f8; --panel: #fff; --ink: #1d2330; --muted: #677085; --line: #d9dde5; --ai: #3567d6; --bad: #d64545; --good: #2f9e5b; }
  @media (prefers-color-scheme: dark) { :root { --bg: #15181e; --panel: #1f242d; --ink: #e6e9ef; --muted: #9aa3b5; --line: #343b48; } }
  body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, sans-serif; }
  main { max-width: 760px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 22px; margin: 0 0 4px; } .muted { color: var(--muted); font-size: 13px; }
  section { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin: 16px 0; }
  label { display: block; margin: 10px 0 4px; font-weight: 600; }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--ink); font: inherit; }
  button { background: var(--ai); color: #fff; border: 0; border-radius: 6px; padding: 8px 16px; font: inherit; cursor: pointer; margin-top: 12px; }
  button:disabled { opacity: .5; cursor: default; }
  .choice { display: flex; gap: 14px; flex-wrap: wrap; } .choice label { font-weight: 400; margin: 4px 0; }
  .err { color: var(--bad); margin-top: 8px; } .bar { height: 10px; background: var(--bg); border-radius: 5px; overflow: hidden; margin-top: 10px; }
  .bar span { display: block; height: 100%; background: var(--ai); width: 0; transition: width .3s; }
  ul { padding-left: 18px; } li { margin: 4px 0; } a { color: var(--ai); }
  .won { color: var(--good); } .lost { color: var(--bad); }
</style>
<main>
  <h1>对局复盘</h1>
  <div class="muted">AI 从你的视角重新思考你的每一步：每个选择的胜率、AI 的选择、关键失误。只支持 Gen 9 OU。全部在你的电脑上运行。</div>
  <section>
    <label for="src">Showdown 回放链接或编号</label>
    <input type="text" id="src" placeholder="https://replay.pokemonshowdown.com/gen9ou-1234567890" />
    <label for="file">或者选择保存的回放文件（.html / .json / .log）</label>
    <input type="file" id="file" accept=".html,.json,.log,.txt" />
    <div><button id="load">读取对局</button></div>
    <div id="pick" hidden>
      <label>你是哪一位玩家？</label><div class="choice" id="players"></div>
      <label>分析强度</label>
      <div class="choice">
        <label><input type="radio" name="strength" value="fast" /> 快速（约半分钟）</label>
        <label><input type="radio" name="strength" value="standard" checked /> 标准（1–2 分钟）</label>
        <label><input type="radio" name="strength" value="deep" /> 深入（约 5 分钟）</label>
      </div>
      <button id="go">开始分析</button>
    </div>
    <div id="progress" hidden><div class="muted" id="ptext">准备中……</div><div class="bar"><span id="pbar"></span></div></div>
    <div class="err" id="err"></div>
  </section>
  <section><b>以前的复盘</b><ul id="list"><li class="muted">还没有。</li></ul></section>
</main>
<script>
const $ = id => document.getElementById(id);
let body = null;
async function post(url, data) {
  const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
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
      `<label><input type="radio" name="player" value="${p.replace(/"/g, "&quot;")}" ${i ? "" : "checked"} /> ${p.replace(/</g, "&lt;")}</label>`).join("");
    $("pick").hidden = false;
  } catch (e) { $("err").textContent = e.message; }
};
$("go").onclick = async () => {
  $("err").textContent = ""; $("go").disabled = true; $("progress").hidden = false;
  try {
    const player = document.querySelector("input[name=player]:checked").value;
    const strength = document.querySelector("input[name=strength]:checked").value;
    const {job} = await post("/api/review", {...body, player, strength});
    const poll = async () => {
      const j = await (await fetch("/api/job/" + job)).json();
      if (j.status == "error") throw new Error(j.error);
      if (j.total) { $("ptext").textContent = `正在分析第 ${j.done} / ${j.total} 步……`; $("pbar").style.width = (100 * j.done / j.total) + "%"; }
      else $("ptext").textContent = j.status == "queued" ? "排队中……" : "正在重建每一步的局面……";
      if (j.status == "done") { location.href = j.url; return; }
      setTimeout(() => poll().catch(e => { $("err").textContent = e.message; $("go").disabled = false; }), 1000);
    };
    await poll();
  } catch (e) { $("err").textContent = e.message; $("go").disabled = false; }
};
fetch("/api/reviews").then(r => r.json()).then(list => {
  if (list.length) $("list").innerHTML = list.map(r =>
    `<li><a href="${r.url}">${r.id}</a> · ${(r.player || "").replace(/</g, "&lt;")} · <span class="${r.won ? "won" : "lost"}">${r.won ? "胜" : "负"}</span> · ${r.turns} 回合 · <span class="muted">${r.date}</span></li>`).join("");
});
</script>
</html>
"""
