"""The review app (2026-10-29): the page server (coach.server) plus a home page where a player
pastes a replay link or picks a saved replay file, chooses which player they were and how deep
to look, and gets the review page when the search is done. Loopback only; one review at a time
(a background thread), progress polled by the page.

  GET  /                      the home page (the reviews so far, the form)
  POST /api/players           {source} or {upload: {name, text}} -> the replay's players, each
                              one's decision count, the machine's search threads
  POST /api/review            {source | upload, player, strength | custom, team, parallel}
                              -> {job}
  POST /api/redo              {review, player, strength | custom, team, parallel} -> {job}: a
                              review's game again, from either player's view (the replay and
                              each player's team kept with its review)
  GET  /api/job/<id>          {status, done, total, url, error}
  POST /api/meta              {review, title, note}: a review renamed / noted on (coach.index)
  GET  /api/reviews?q=&sort=&order=&page=&size=   the home page's list (coach.index.query)
  GET  /api/redo-info?review= what the review page's "review again" form needs
  GET  /coach/<review>/viewer.html   the review page, rendered anew (the current page's code)
"""

import json
import os
import queue
import re
import threading
import uuid
from dataclasses import asdict
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from alpha_poke import paths
from alpha_poke.coach import form, index, narrate, replays, server, viewer
from alpha_poke.coach.review import decision_count, review
from alpha_poke.coach.team import KnownSet, TeamError, load_team, match_team
from alpha_poke.replay import parse_replay
from alpha_poke.selfplay.runner import MODEL

# search effort per decision: (belief worlds, milliseconds, independent searches -- their spread
# gives the values' errors, 2026-10-30)
STRENGTH = {"fast": (8, 500, 1), "standard": (16, 2000, 3), "deep": (32, 3000, 5)}
LIMITS = {"worlds": (4, 64), "ms": (200, 10_000), "repeats": (1, 8)}  # (a custom strength's)


def custom_strength(c: dict) -> tuple[int, int, int]:
    """A custom strength {worlds, seconds, repeats} within LIMITS."""
    clamp = lambda k, v: int(min(max(v, LIMITS[k][0]), LIMITS[k][1]))  # noqa: E731
    return (clamp("worlds", float(c.get("worlds", 16))), clamp("ms", 1000 * float(c.get("seconds", 2))),
            clamp("repeats", float(c.get("repeats", 3))))  # fmt: skip


COACH = paths.DATA / "coach"
# the messages the page shows, in its interface language (the request's "lang")
MESSAGES = {
    "no_source": {"en": "Paste a replay link or id, or pick a replay file.",
                  "zh": "请粘贴回放链接或编号，或者选择一个回放文件。"},
    "not_a_link": {"en": "Paste a Showdown replay link or id.", "zh": "请粘贴 Showdown 回放链接或编号。"},
    "format": {"en": "Only Gen 9 OU games can be reviewed (this one: {fmt}).",
               "zh": "只支持 Gen 9 OU 的对局（这一局：{fmt}）。"},
    "player": {"en": "Choose which player you were.", "zh": "请选择你是哪一位玩家。"},
    "no_review": {"en": "That review is not there any more.", "zh": "找不到这份复盘了。"},
    "team_unreadable": {"en": "The team could not be read: paste it as Showdown's teambuilder exports it.",
                        "zh": "队伍读不出来：请粘贴 Showdown 队伍编辑器“导出”的文本。"},
    "team_fetch": {"en": "The PokéPaste link could not be fetched ({names}).",
                   "zh": "PokéPaste 链接读取失败（{names}）。"},
    "team_mismatch": {"en": "The team does not fit this game ({names}).",
                      "zh": "队伍和这局对不上（{names}）。"},
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

    def max_parallel(self) -> int:
        """Searches at once the machine has the cores for (each ``threads`` threads)."""
        return max(1, (os.cpu_count() or 2) // self.threads)

    def submit(self, row: dict, player: str, strength, team=None, parallel: int = 2) -> str:
        """``strength``: a preset's name or (worlds, ms, repeats); ``team``: the player's sets
        (coach.team); ``parallel``: searches at once."""
        jid = uuid.uuid4().hex[:12]
        self.jobs[jid] = {"status": "queued", "done": 0, "total": 0, "url": None, "error": None}
        parallel = int(min(max(parallel, 1), self.max_parallel()))
        self.queue.put((jid, row, player, strength, team, parallel))
        return jid

    def _work(self) -> None:
        while True:
            jid, row, player, strength, team, parallel = self.queue.get()
            job = self.jobs[jid]
            try:
                job["status"] = "running"
                side = replays.side_of(row, player)
                worlds, ms, repeats = (strength if isinstance(strength, tuple)
                                       else self.strengths.get(strength, self.strengths["standard"]))  # fmt: skip

                def progress(done, total, job=job):
                    job["done"], job["total"] = done, total

                rep = review(row, side, self.belief(), self.model or model_dir(), worlds=worlds, ms=ms, repeats=repeats,
                             threads=self.threads, log=lambda *_: None, progress=progress, team=team,
                             parallel=parallel)  # fmt: skip
                job["url"] = f"/coach/{save(rep, row, team).name}/viewer.html"
                job["status"] = "done"
            except Exception as e:  # noqa: BLE001 - shown on the page
                job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"


def save(rep: dict, row: dict, team: dict | None = None) -> Path:
    """A review's files in data/coach/<id>-<side>: the report, its summary, the page, and what
    reviewing it again needs -- the replay and the player's team (when one was given)."""
    out = COACH / f"{row['id']}-{rep['side']}"
    out.mkdir(parents=True, exist_ok=True)

    def dump(name: str, obj) -> None:
        (out / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

    dump("review.json", rep)
    dump("replay.json", row)
    if team:
        dump("team.json", {k: asdict(v) for k, v in team.items()})
    (out / "summary.md").write_text(narrate.summary(rep), encoding="utf-8")
    page = viewer.render(rep, row, client="local", title=index.title_of(COACH, out.name))
    (out / "viewer.html").write_text(page, encoding="utf-8")
    return out


REVIEW_NAME = re.compile(r"[A-Za-z0-9_-]+")


def stored(name: str) -> tuple[dict, dict, dict | None]:
    """A saved review's (report, replay, team): the replay from replay.json, or (a review saved
    before it was kept) the log in its page; Refused "no_review" when there is none."""
    d = COACH / (name or "")
    if not REVIEW_NAME.fullmatch(name or "") or not (d / "review.json").is_file():
        raise Refused("no_review")
    rep = json.loads((d / "review.json").read_text(encoding="utf-8"))
    if (d / "replay.json").is_file():
        row = json.loads((d / "replay.json").read_text(encoding="utf-8"))
    else:
        page = (d / "viewer.html").read_text(encoding="utf-8")
        m = re.search(r'class="battle-log-data">(.*?)</script>', page, re.S)
        if m is None:
            raise Refused("no_review")
        row = replays.from_json({"id": rep["id"], "log": m.group(1).replace("<\\/", "</")})
    return rep, row, stored_team(d)


def stored_team(d: Path) -> dict | None:
    """The team a review in ``d`` was given (team.json), if any."""
    if not (d / "team.json").is_file():
        return None
    sets = json.loads((d / "team.json").read_text(encoding="utf-8"))
    return {k: KnownSet(**{f: tuple(x) if f in ("evs", "ivs") and x else x for f, x in v.items()})
            for k, v in sets.items()}  # fmt: skip


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


def reviews(qs: dict) -> dict:
    """The home page's list (coach.index.query) for the query string ``qs`` (q, sort, order,
    page, size), the index brought up to date first."""
    index.sync(COACH, stored)
    get = lambda k, d: (qs.get(k) or [d])[0]  # noqa: E731
    try:
        page, size = int(get("page", 1)), int(get("size", 20))
    except ValueError:
        page, size = 1, 20
    return index.query(COACH, get("q", ""), get("sort", "reviewed"), get("order", "desc") != "asc",
                       page, size)  # fmt: skip


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
                return self._json(reviews(parse_qs(urlsplit(self.path).query)))
            if path == "/api/redo-info":
                try:
                    rep, row, team = stored(
                        parse_qs(urlsplit(self.path).query).get("review", [""])[0]
                    )
                except Refused:
                    return self._json({"error": "no such review"}, HTTPStatus.NOT_FOUND)
                # (either player's view: the other's review, when there is one, linked)
                other = "p2" if rep["side"] == "p1" else "p1"
                other_dir = COACH / f"{rep['id']}-{other}"
                return self._json({"strengths": jobs.strengths, "max_parallel": jobs.max_parallel(),
                                   "threads": jobs.threads, "players": row["players"],
                                   "decisions": [decision_count(row, s) for s in ("p1", "p2")],
                                   "player": rep["player"], "team": team is not None,
                                   "settings": rep["settings"],
                                   "other": (f"/coach/{other_dir.name}/viewer.html"
                                             if (other_dir / "review.json").is_file() else None)})  # fmt: skip
            m = re.fullmatch(r"/coach/([A-Za-z0-9_-]+)/viewer\.html", path)
            if m:  # (rendered anew: a review from before has the current page's code too)
                try:
                    rep, row, _ = stored(m.group(1))
                    page = viewer.render(
                        rep, row, client="local", title=index.title_of(COACH, m.group(1))
                    )
                except Refused:
                    page = None
                if page is not None:
                    return self._send(page.encode(), "text/html; charset=utf-8")
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
            kept = None
            try:
                body = json.loads(self.rfile.read(min(n, 20_000_000)) or b"{}")
                lang = body.get("lang") or "en"
                if self.path == "/api/meta":  # (a review renamed / noted on: its id and link stay)
                    index.sync(COACH, stored)
                    if not index.set_meta(COACH, str(body.get("review") or ""), str(body.get("title") or ""),
                                          str(body.get("note") or "")):  # fmt: skip
                        raise Refused("no_review")
                    return self._json({"ok": True})
                if self.path == "/api/redo":  # (the review's game, its player, its team)
                    rep, row, kept = stored(body.get("review") or "")
                    # (another player's view: its own review; the team kept is this player's)
                    if body.get("player") not in row["players"]:
                        body["player"] = rep["player"]
                    if body["player"] != rep["player"]:
                        kept = stored_team(
                            COACH / f"{row['id']}-{replays.side_of(row, body['player'])}"
                        )
                else:
                    row = load_row(body)
            except Refused as e:
                return self._json({"error": message(str(e), lang)}, HTTPStatus.BAD_REQUEST)
            except Exception as e:  # noqa: BLE001 - the page shows it
                return self._json({"error": str(e) or type(e).__name__}, HTTPStatus.BAD_REQUEST)
            if not row.get("formatid", "").startswith("gen9ou"):
                return self._json({"error": message("format", lang, fmt=row.get("formatid"))},
                                  HTTPStatus.BAD_REQUEST)  # fmt: skip
            if self.path == "/api/players":
                return self._json({"id": row["id"], "players": row["players"],
                                   "decisions": [decision_count(row, s) for s in ("p1", "p2")],
                                   "max_parallel": jobs.max_parallel(), "threads": jobs.threads,
                                   "strengths": jobs.strengths})  # fmt: skip
            if self.path in ("/api/review", "/api/redo"):
                player = body.get("player") or ""
                if player not in row["players"]:
                    return self._json({"error": message("player", lang)}, HTTPStatus.BAD_REQUEST)
                team = kept  # (a review again: the team given before, unless another is pasted)
                if (body.get("team") or "").strip():  # (checked now: the page shows what is wrong)
                    try:
                        side = replays.side_of(row, player)
                        records = [m for m in parse_replay(row).teams[side] if not m.phantom]
                        team = match_team(load_team(body["team"]), records)
                    except TeamError as e:
                        return self._json({"error": message(e.code, lang, names=e.names)},
                                          HTTPStatus.BAD_REQUEST)  # fmt: skip
                strength = (custom_strength(body["custom"]) if body.get("custom")
                            else body.get("strength") or "standard")  # fmt: skip
                try:
                    parallel = int(body.get("parallel") or 2)
                except (TypeError, ValueError):
                    parallel = 2
                return self._json({"job": jobs.submit(row, player, strength, team, parallel)})
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
  main { max-width: 1240px; margin: 0 auto; padding: 24px 16px; } .narrow { max-width: 820px; }
  .top { display: flex; align-items: baseline; gap: 12px; } .top .lang { margin-left: auto; font-size: 12px; color: var(--muted); }
  .lang button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); padding: 2px 8px; cursor: pointer; font: inherit; margin: 0; border-radius: 0; }
  .lang button.sel { background: var(--ai); color: #fff; border-color: var(--ai); }
  h1 { font-size: 22px; margin: 0 0 4px; } .muted { color: var(--muted); font-size: 13px; }
  section { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; margin: 16px 0; }
  label { display: block; margin: 10px 0 4px; font-weight: 600; }
  input[type=text] { width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--ink); font: inherit; }
  .go { background: var(--ai); color: #fff; border: 0; border-radius: 6px; padding: 8px 16px; font: inherit; cursor: pointer; margin-top: 12px; }
  .choice { display: flex; gap: 14px; flex-wrap: wrap; } .choice label { font-weight: 400; margin: 4px 0; }
  .err { color: var(--bad); margin-top: 8px; }
__RF_CSS__  ul { padding-left: 18px; } li { margin: 4px 0; } a { color: var(--ai); }
  .won { color: var(--good); } .lost { color: var(--bad); }
  .lhead { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .lhead input[type=search] { flex: 1 1 200px; max-width: 340px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--ink); font: inherit; }
  .lhead label, .pager label { display: inline; margin: 0; font-weight: 400; font-size: 13px; color: var(--muted); }
  select { background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 4px; font: inherit; }
  .tablewrap { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th { text-align: left; font-weight: 600; color: var(--muted); font-size: 12px; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; user-select: none; }
  th[data-sort] { cursor: pointer; } th[data-sort]:hover { color: var(--ink); } th.on { color: var(--ai); }
  td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; } td.nw { white-space: nowrap; }
  .sub { font-size: 12px; color: var(--muted); } a b { color: var(--ai); }
  .picon { display: inline-block; width: 40px; height: 30px; vertical-align: middle; }
  .pname { font-size: 12px; margin-right: 6px; } .teams div { white-space: nowrap; }
  .note { max-width: 240px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .edit { background: none; border: 1px solid var(--line); color: var(--muted); border-radius: 4px; cursor: pointer; font: inherit; padding: 1px 7px; }
  .edit:hover { color: var(--ai); border-color: var(--ai); }
  tr.editor td { background: var(--bg); }
  .editor input, .editor textarea { width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--ink); font: inherit; margin: 4px 0; }
  .editor textarea { min-height: 4em; }
  .editor .go { margin: 4px 8px 0 0; padding: 5px 14px; } .editor .plain { background: none; color: var(--ink); border: 1px solid var(--line); }
  .pager { display: flex; gap: 10px; align-items: center; justify-content: flex-end; margin-top: 10px; font-size: 13px; }
  .pager button { background: var(--bg); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; padding: 3px 10px; cursor: pointer; font: inherit; }
  .pager button:disabled { opacity: .4; cursor: default; }
</style>
<script>window.exports = window;</script>
<script src="/js/lib/ps-polyfill.js"></script><script src="/config/config.js"></script>
<script src="/js/lib/jquery-1.11.0.min.js"></script><script src="/js/battledata.js"></script>
<script src="/data/pokedex.js"></script>
<main>
  <div class="top"><h1 data-t="title"></h1>
    <span class="lang"><span data-t="ui"></span> <button data-v="en">EN</button><button data-v="zh">中文</button></span></div>
  <div class="muted narrow" data-t="intro"></div>
  <section><div class="narrow">
    <label for="src" data-t="link"></label>
    <input type="text" id="src" placeholder="https://replay.pokemonshowdown.com/gen9ou-1234567890" />
    <label for="file" data-t="fileLabel"></label>
    <input type="file" id="file" accept=".html,.json,.log,.txt" />
    <div><button class="go" id="load" data-t="load"></button></div>
    <div id="pick" hidden>
      <label data-t="which"></label><div class="choice" id="players"></div>
__RF_HTML__
    </div>
    <div class="err" id="err"></div>
  </div></section>
  <section>
    <div class="lhead"><b data-t="past"></b><input type="search" id="q" />
      <label><span data-t="perPage"></span> <select id="size"><option>10</option><option>20</option><option>50</option><option>100</option></select></label></div>
    <div class="tablewrap"><table><thead><tr>
      <th data-sort="title" data-t="colGame"></th><th data-sort="played" data-t="colPlayed"></th><th data-sort="won" data-t="colResult"></th>
      <th data-t="colTeams"></th><th data-sort="top1" data-t="colTop1"></th><th data-sort="mean_loss" data-t="colLoss"></th>
      <th data-sort="bad" data-t="colBad"></th><th data-t="colSettings"></th><th data-sort="reviewed" data-t="colReviewed"></th>
      <th data-t="colNote"></th><th></th>
    </tr></thead><tbody id="rows"></tbody></table></div>
    <div class="pager"><button id="prev">‹</button><span id="pageinfo"></span><button id="next">›</button></div>
  </section>
</main>
<script>
__RF_JS__
const T = {
  en: {title: "Game review", ui: "Interface",
       intro: "An AI rethinks each of your decisions from your side of the game: every option's winning chance, the AI's choice, the key mistakes. Gen 9 OU only. Everything runs on your computer.",
       link: "Showdown replay link or id", fileLabel: "or a saved replay file (.html / .json / .log)", load: "Load the game",
       which: "Which player were you?", past: "Reviews so far", none: "None yet.", noMatch: "Nothing matches.",
       search: "Search: name, note, player, Pokémon, id", perPage: "per page",
       colGame: "Game (reviewed player first)", colPlayed: "Played", colResult: "Result", colTeams: "Teams",
       colTop1: "AI's first choice", colLoss: "Avg. loss", colBad: "Disagreed", colSettings: "Analysis",
       colReviewed: "Reviewed", colNote: "Note", edit: "Rename / note", teamPasted: "team pasted", pts: "pts",
       titlePh: "Name (empty: the players)", notePh: "Note", save: "Save", cancel: "Cancel",
       pageOf: (p, n, t) => `page ${p} of ${n} · ${t} reviews`,
       won: "won", lost: "lost", turns: n => `${n} turns`},
  zh: {title: "对局复盘", ui: "界面",
       intro: "AI 从你的视角重新思考你的每一步：每个选择的胜率、AI 的选择、关键失误。只支持 Gen 9 OU。全部在你的电脑上运行。",
       link: "Showdown 回放链接或编号", fileLabel: "或者选择保存的回放文件（.html / .json / .log）", load: "读取对局",
       which: "你是哪一位玩家？", past: "以前的复盘", none: "还没有。", noMatch: "没有符合的复盘。",
       search: "搜索：名称、备注、玩家、宝可梦、编号", perPage: "每页",
       colGame: "对局（被分析的玩家在前）", colPlayed: "比赛时间", colResult: "结果", colTeams: "双方队伍",
       colTop1: "AI 一选吻合", colLoss: "平均损失", colBad: "不认同", colSettings: "分析设置",
       colReviewed: "复盘时间", colNote: "备注", edit: "重命名 / 备注", teamPasted: "已贴队伍", pts: "点",
       titlePh: "名称（留空就显示双方玩家）", notePh: "备注", save: "保存", cancel: "取消",
       pageOf: (p, n, t) => `第 ${p} / ${n} 页 · 共 ${t} 份`,
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
    $("players").innerHTML = r.players.map((p, i) => p ?
      `<label><input type="radio" name="player" value="${esc(p)}" ${i == r.players.findIndex(Boolean) ? "checked" : ""} /> ${esc(p)}</label>` : "").join("");
    const player = () => document.querySelector("input[name=player]:checked").value;
    const form = reviewForm(UI, r, {
      decisions: () => r.decisions[Math.max(0, r.players.indexOf(player()))],
      submit: v => post("/api/review", {...body, player: player(), ...v}).then(j => j.job),
      done: url => { location.href = url; },
    });
    document.querySelectorAll("input[name=player]").forEach(x => { x.onchange = form.estimate; });
    $("pick").hidden = false;
  } catch (e) { $("err").textContent = e.message; }
};
// the reviews so far: searched, sorted and paged by the server (coach.index); the sort and the
// page size remembered; a row renamed / noted on in place
const remembered = (k, d) => { try { return localStorage.getItem("coach-list-" + k) || d; } catch (e) { return d; } };
const remember = (k, v) => { try { localStorage.setItem("coach-list-" + k, v); } catch (e) {} };
const view = {q: "", sort: remembered("sort", "reviewed"), order: remembered("order", "desc"), page: 1, size: +remembered("size", 20)};
let list = {rows: [], total: 0, page: 1, pages: 1}, editing = null;
const idOf = x => String(x || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const when = t => t ? new Date(t * 1000).toLocaleString(UI == "zh" ? "zh-CN" : "en-GB",
  {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"}) : "—";
function monName(sp) {
  const t = UI == "zh" && window.BattleText && BattleText["zh-cn"] && BattleText["zh-cn"].Pokedex;
  return (t && t[idOf(sp)] && t[idOf(sp)].name) || sp;
}
const icons = team => team.map(sp => window.Dex && Dex.getPokemonIcon
  ? `<span class="picon" style="${esc(Dex.getPokemonIcon(sp))}" title="${esc(monName(sp))}"></span>`
  : `<span class="pname">${esc(monName(sp))}</span>`).join("");
const pct = x => x == null ? "—" : Math.round(100 * x) + "%";
function rowHTML(r) {
  const vs = `${esc(r.player)} <span class="sub">vs</span> ${esc(r.opponent)}`;
  const game = (r.title ? `<a href="${r.url}"><b>${esc(r.title)}</b></a><div class="sub">${vs}</div>` : `<a href="${r.url}"><b>${vs}</b></a>`)
    + `<div class="sub">${esc(r.id)}</div>`;
  const settings = `${r.repeats} × ${r.ms / 1000} s · ${r.worlds}` + (r.team ? `<div class="sub">${L.teamPasted}</div>` : "");
  let h = `<tr><td>${game}</td><td class="nw">${when(r.played)}</td>`
    + `<td class="nw"><span class="${r.won ? "won" : "lost"}">${r.won ? L.won : L.lost}</span><div class="sub">${L.turns(r.turns)}</div></td>`
    + `<td class="teams"><div>${icons(r.teams[0])}</div><div>${icons(r.teams[1])}</div></td>`
    + `<td class="num">${pct(r.top1)}<div class="sub">${r.decisions ? Math.round((r.top1 || 0) * r.decisions) + "/" + r.decisions : ""}</div></td>`
    + `<td class="num">${r.mean_loss == null ? "—" : (100 * r.mean_loss).toFixed(1) + " " + L.pts}</td>`
    + `<td class="num"><span class="lost">${r.bad}</span> / ${r.mild}</td><td class="nw">${settings}</td>`
    + `<td class="nw">${when(r.reviewed)}</td><td><div class="note">${esc(r.note || "")}</div></td>`
    + `<td><button class="edit" data-dir="${esc(r.dir)}" title="${L.edit}">✎</button></td></tr>`;
  if (editing == r.dir) h += `<tr class="editor"><td colspan="11"><input id="e-title" maxlength="120" placeholder="${esc(L.titlePh)}" value="${esc(r.title || "")}" />`
    + `<textarea id="e-note" maxlength="2000" placeholder="${esc(L.notePh)}">${esc(r.note || "")}</textarea>`
    + `<button class="go" id="e-save">${L.save}</button><button class="go plain" id="e-cancel">${L.cancel}</button><span class="err" id="e-err"></span></td></tr>`;
  return h;
}
function show() {
  $("rows").innerHTML = list.rows.length ? list.rows.map(rowHTML).join("")
    : `<tr><td colspan="11" class="muted">${view.q ? L.noMatch : L.none}</td></tr>`;
  document.querySelectorAll("th[data-sort]").forEach(th => {
    const on = th.dataset.sort == view.sort; th.classList.toggle("on", on);
    th.textContent = L[th.dataset.t] + (on ? (view.order == "asc" ? " ▲" : " ▼") : "");
  });
  $("pageinfo").textContent = L.pageOf(list.page, list.pages, list.total);
  $("prev").disabled = list.page <= 1; $("next").disabled = list.page >= list.pages;
  const r = list.rows.find(x => x.dir == editing);
  if (r) {
    $("e-title").focus();
    $("e-cancel").onclick = () => { editing = null; show(); };
    $("e-save").onclick = async () => {
      try { await post("/api/meta", {review: r.dir, title: $("e-title").value, note: $("e-note").value}); editing = null; await load(); }
      catch (e) { $("e-err").textContent = e.message; }
    };
  }
}
async function load() {
  const p = new URLSearchParams({q: view.q, sort: view.sort, order: view.order, page: view.page, size: view.size});
  list = await (await fetch("/api/reviews?" + p)).json();
  view.page = list.page; show();
}
$("q").placeholder = L.search;
let typing = null;
$("q").oninput = () => { clearTimeout(typing); typing = setTimeout(() => { view.q = $("q").value; view.page = 1; load(); }, 300); };
$("size").value = String(view.size);
$("size").onchange = () => { view.size = +$("size").value; view.page = 1; remember("size", view.size); load(); };
$("prev").onclick = () => { view.page--; load(); };
$("next").onclick = () => { view.page++; load(); };
document.querySelectorAll("th[data-sort]").forEach(th => { th.onclick = () => {
  const k = th.dataset.sort;
  if (view.sort == k) view.order = view.order == "asc" ? "desc" : "asc";
  else { view.sort = k; view.order = k == "title" || k == "mean_loss" || k == "bad" ? "asc" : "desc"; }
  view.page = 1; remember("sort", view.sort); remember("order", view.order); load();
}; });
$("rows").onclick = e => { const b = e.target.closest(".edit"); if (b) { editing = editing == b.dataset.dir ? null : b.dataset.dir; show(); } };
load();
// (the Pokémon's Chinese names: Showdown's text data, then the rows again)
if (UI == "zh" && window.Dex && Dex.loadTextData) {
  const orig = Dex.prefs; Dex.prefs = function (p) { return p == "language" ? "zh-cn" : orig.call(Dex, p); };
  Dex.loadTextData("zh-cn").then(show, () => {});
}
</script>
</html>
"""
HOME = form.embed(HOME)
