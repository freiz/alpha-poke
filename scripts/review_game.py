"""Review one player's game (alpha_poke.coach): each decision searched from that player's view,
the decisions that cost the most, the swings; optionally a coach's write-up by a chat model.

  uv run python scripts/review_game.py data/public_games/20261029/replays/<file>.html --player <name>
  uv run python scripts/review_game.py gen9ou-2706511006 --player <name> --llm
  uv run python scripts/review_game.py https://replay.pokemonshowdown.com/gen9ou-... --player <name> --open

--open: the review page in the browser when done (starting the page server,
scripts/review_server.py, if it is not running: Ctrl-C stops it).

Writes data/coach/<replay id>-<side>/: review.json (every decision: options, winning chances,
the public state, the turn's events), summary.md, viewer.html (the replay with the review, served
by scripts/review_server.py), viewer-online.html (the same, the player from Showdown's site: open
the file), and with --llm coach.md (.env:
COACH_LLM_BASE_URL / COACH_LLM_API_KEY / COACH_LLM_MODEL, an OpenAI-compatible endpoint).
CPU: one search of --ms per decision (--threads); nice it while a bot plays (time-based search).
Players' names stay in data/ (local): the reports say ME / OPP.
"""

import argparse
import json
import sys

from alpha_poke import paths
from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.coach import narrate, replays, server, viewer
from alpha_poke.coach.review import review
from alpha_poke.selfplay.runner import MODEL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay", help="a replay file (.html / .json / log), a replay id or URL")
    ap.add_argument("--player", required=True, help="whose decisions to review")
    ap.add_argument("--model", default=MODEL, help="the network (default: the released one)")
    ap.add_argument("--worlds", type=int, default=16, help="belief worlds per decision")
    ap.add_argument("--ms", type=int, default=2000, help="search time per decision")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--llm", action="store_true", help="also the chat model's write-up")
    ap.add_argument("--language", default="Chinese (简体中文)")
    ap.add_argument("--from-json", action="store_true", help="reuse review.json (no search)")
    ap.add_argument("--open", action="store_true", help="open the review page in the browser")
    ap.add_argument("--port", type=int, default=8090, help="the page server's port (--open)")
    a = ap.parse_args()
    row = replays.load(a.replay)
    side = replays.side_of(row, a.player)
    out = paths.DATA / "coach" / f"{row['id']}-{side}"
    out.mkdir(parents=True, exist_ok=True)
    if a.from_json and (out / "review.json").exists():
        rep = json.loads((out / "review.json").read_text())
    else:
        print(f"{row['id']}: reviewing {side}'s decisions ({a.ms} ms x {a.threads} threads each)")
        rep = review(row, side, BeliefModel.load(), a.model, worlds=a.worlds, ms=a.ms,
                     threads=a.threads)  # fmt: skip
        (out / "review.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    (out / "summary.md").write_text(narrate.summary(rep))
    # the review page: through scripts/review_server.py (Showdown's player from a local cache), and
    # one that loads the player from Showdown's site (open the file itself)
    (out / "viewer.html").write_text(viewer.render(rep, row, client="local"))
    (out / "viewer-online.html").write_text(viewer.render(rep, row, client="official"))
    print(narrate.summary(rep))
    if a.llm:
        (out / "coach.md").write_text(narrate.write_up(rep, a.language))
        print(f"coach's write-up: {out / 'coach.md'}")
    print(f"written: {out}")
    if a.open:
        url = f"http://localhost:{a.port}/coach/{out.name}/viewer.html"
        httpd = None if server.running(a.port) else server.serve(a.port)
        server.open_page(url)
        print(f"opened {url}")
        if httpd is not None:
            print("serving the page; Ctrl-C stops")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
