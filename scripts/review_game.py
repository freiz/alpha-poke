"""Review one player's game (alpha_poke.coach): each decision searched from that player's view,
the decisions that cost the most, the swings; optionally a coach's write-up by a chat model.

  uv run python scripts/review_game.py data/public_games/20261029/replays/<file>.html --player <name>
  uv run python scripts/review_game.py gen9ou-2706511006 --player <name> --llm
  uv run python scripts/review_game.py https://replay.pokemonshowdown.com/gen9ou-... --player <name>

Writes data/coach/<replay id>-<side>/: review.json (every decision: options, winning chances,
the public state, the turn's events), summary.md, and with --llm coach.md (.env:
COACH_LLM_BASE_URL / COACH_LLM_API_KEY / COACH_LLM_MODEL, an OpenAI-compatible endpoint).
CPU: one search of --ms per decision (--threads); nice it while a bot plays (time-based search).
Players' names stay in data/ (local): the reports say ME / OPP.
"""

import argparse
import json
import sys

from alpha_poke import paths
from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.coach import narrate, replays
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
    print(narrate.summary(rep))
    if a.llm:
        (out / "coach.md").write_text(narrate.write_up(rep, a.language))
        print(f"coach's write-up: {out / 'coach.md'}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
