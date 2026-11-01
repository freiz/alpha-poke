"""All of the review app's metagame knowledge from one entry (2026-10-30): its team analysis
(coach.meta) and archetypes (teams.archetypes) read one snapshot shipped with the app
(src/alpha_poke/coach/meta_knowledge.json.gz); this fetches the sources, builds a candidate,
checks it (teams.knowledge_checks: the rules of the game today, the sources, the snapshot it
replaces, the engine) and ships it only when no check fails.

  uv run python scripts/knowledge.py status      # the shipped snapshot: built from what, how old
  uv run python scripts/knowledge.py fetch       # new replays (the polite crawler: hours),
                                                 # Smogon's months, archived PokéPastes, then the
                                                 # catalog with the forum's cached teams
                                                 # (deduplicated: teams.catalog)
  uv run python scripts/knowledge.py build       # -> data/derived/teams/knowledge/candidate.json.gz
  uv run python scripts/knowledge.py validate    # the checks -> report (markdown) + exit 1 on a fail
  uv run python scripts/knowledge.py promote     # the validated candidate -> the shipped snapshot
  uv run python scripts/knowledge.py all         # build, validate, promote (--fetch: fetch first);
                                                 # stops at the first failure
  uv run python scripts/knowledge.py check       # the checks on the shipped snapshot itself (after a
                                                 # Showdown update: a new ban fails it)

Options after the step go to it: fetch --hours / --new / --skip-replays /
--pastes N (archived pastes fetched this time; 0 = none) / --skip-pastes, build
(scripts/build_meta_knowledge.py's own: --meta-days, --top, ...), validate --damage-pairs. Run
the heavy steps under a memory cap (systemd-run --user --scope -p MemoryMax=24G ...); commit the
promoted snapshot with its report's summary (data/derived/teams/knowledge/report-<built>.md).
"""

import argparse
import gzip
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from alpha_poke import paths  # noqa: E402
from alpha_poke.coach.meta import SNAPSHOT  # noqa: E402

DIR = paths.TEAM_DATA / "knowledge"
CANDIDATE = DIR / "candidate.json.gz"
VERDICT = DIR / "candidate.checks.json"  # the candidate's last validation (its sha and checks)


def read(path: Path) -> dict | None:
    return json.loads(gzip.decompress(path.read_bytes())) if path.exists() else None


def sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def run(*cmd: str) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run([sys.executable, *cmd], check=True)


def status(_argv) -> int:
    from alpha_poke.coach import meta

    snap = meta.load()
    if not snap:
        print("no shipped snapshot")
        return 1
    src = snap.get("sources", {})
    print(f"shipped: built {snap['built']}, games to {src.get('games_to')}, Smogon {src.get('smogon_month')}, "
          f"Showdown {src.get('showdown', '?')}; {len(snap['threats'])} threats, "
          f"{len(snap['metagame'])} compositions, archetypes: {'yes' if snap.get('archetypes') else 'no'}")  # fmt: skip
    if CANDIDATE.exists():
        c = read(CANDIDATE)
        v = json.loads(VERDICT.read_text()) if VERDICT.exists() else {}
        ok = v.get("sha") == sha(CANDIDATE)
        print(f"candidate: built {c['built']}; validation: "
              f"{(v.get('summary') if ok else 'none (or out of date)')}")  # fmt: skip
    return 0


def fetch(argv) -> int:
    ap = argparse.ArgumentParser(prog="knowledge.py fetch")
    ap.add_argument("--hours", type=float, default=1.5, help="the replay listing's time")
    ap.add_argument("--new", type=int, default=20000, help="replays to download (>= 1500, 25 days)")
    ap.add_argument("--download-hours", type=float, default=5.0)
    ap.add_argument("--skip-replays", action="store_true")
    ap.add_argument(
        "--pastes",
        type=int,
        default=3000,
        help="archived PokéPastes fetched this time (2 s each; the rest next time)",
    )
    ap.add_argument("--skip-pastes", action="store_true")
    a = ap.parse_args(argv)
    if not a.skip_replays:
        run(
            "scripts/crawl_replays.py",
            "--max-hours",
            str(a.hours),
            "list",
            "--mode",
            "new",
            "--pages",
            "2000",
        )
        db = sqlite3.connect(paths.REPLAYS / "index.sqlite")
        done = db.execute("SELECT COUNT(*) FROM replays WHERE status='done'").fetchone()[0]
        run("scripts/crawl_replays.py", "--max-hours", str(a.download_hours), "download", "--target",
            str(done + a.new), "--min-rating", "1500", "--since-days", "25")  # fmt: skip
    run("scripts/fetch_smogon_stats.py", "--months", "2")
    # the teams: the archived pastes (scripts/harvest_pastes.py: the archive's index again, the
    # next --pastes pages, the gen9ou ones as links; the forum is not read again: its threads
    # turn crawlers away since 2026-10-31, its cached teams stay in the links) -- then the
    # catalog: one validation per paste, one entry per canonical team, near-duplicates in
    # families (teams.catalog)
    if not a.skip_pastes:
        run("scripts/harvest_pastes.py", "list", "--refresh")
        if a.pastes > 0:
            run("scripts/harvest_pastes.py", "fetch", "--max", str(a.pastes))
        run("scripts/harvest_pastes.py", "links")
        run("scripts/teams.py", "build")
    return 0


def build(argv) -> int:
    import build_meta_knowledge as bmk

    a = bmk.args([*argv, "--out", str(CANDIDATE)])
    t = time.time()
    bmk.write(bmk.build(a), CANDIDATE)
    VERDICT.unlink(missing_ok=True)
    print(
        f"{CANDIDATE}: {CANDIDATE.stat().st_size // 1024} KB in {time.time() - t:.0f} s; next: validate"
    )
    return 0


def _validate(snap: dict, prev: dict | None, pairs: int) -> tuple[list[dict], str]:
    from alpha_poke.teams import knowledge_checks as K

    checks = K.run(snap, prev, pairs)
    return checks, K.report(checks, snap, prev)


def _summary(checks: list[dict]) -> str:
    n = {s: sum(c["status"] == s for c in checks) for s in ("pass", "warn", "fail")}
    return f"{n['pass']} pass, {n['warn']} warn, {n['fail']} fail"


def validate(argv) -> int:
    ap = argparse.ArgumentParser(prog="knowledge.py validate")
    ap.add_argument("--damage-pairs", type=int, default=1500)
    a = ap.parse_args(argv)
    snap = read(CANDIDATE)
    if snap is None:
        print("no candidate: build first")
        return 1
    checks, text = _validate(snap, read(SNAPSHOT), a.damage_pairs)
    out = DIR / f"report-{snap['built']}.md"
    out.write_text(text)
    for c in checks:
        if c["status"] != "pass":
            print(f"  {c['status'].upper():4} {c['name']}: {c['detail']}")
    summary = _summary(checks)
    VERDICT.write_text(json.dumps({"sha": sha(CANDIDATE), "summary": summary, "checks": checks}))
    print(f"{summary} -- {out}")
    return 1 if "fail" in {c["status"] for c in checks} else 0


def promote(_argv) -> int:
    v = json.loads(VERDICT.read_text()) if VERDICT.exists() else {}
    if not CANDIDATE.exists() or v.get("sha") != sha(CANDIDATE):
        print("the candidate has no validation of its own: validate first")
        return 1
    if any(c["status"] == "fail" for c in v["checks"]):
        print(f"not promoted: {v['summary']}")
        return 1
    snap = read(CANDIDATE)
    snap["checks"] = {"summary": v["summary"],
                      "warnings": [f"{c['name']}: {c['detail']}" for c in v["checks"] if c["status"] == "warn"]}  # fmt: skip
    SNAPSHOT.write_bytes(gzip.compress(json.dumps(snap, separators=(",", ":")).encode(), 9))
    shutil.copy(DIR / f"report-{snap['built']}.md", DIR / "report-shipped.md")
    print(f"{SNAPSHOT} <- candidate built {snap['built']} ({v['summary']}); commit it")
    return 0


def check(argv) -> int:
    ap = argparse.ArgumentParser(prog="knowledge.py check")
    ap.add_argument("--damage-pairs", type=int, default=600)
    a = ap.parse_args(argv)
    snap = read(SNAPSHOT)
    checks, text = _validate(snap, None, a.damage_pairs)
    (DIR / "report-shipped-check.md").write_text(text)
    for c in checks:
        if c["status"] != "pass":
            print(f"  {c['status'].upper():4} {c['name']}: {c['detail']}")
    print(_summary(checks), "--", DIR / "report-shipped-check.md")
    return 1 if "fail" in {c["status"] for c in checks} else 0


def all_steps(argv) -> int:
    ap = argparse.ArgumentParser(prog="knowledge.py all")
    ap.add_argument("--fetch", action="store_true")
    a, rest = ap.parse_known_args(argv)
    steps = ([lambda: fetch([])] if a.fetch else []) + [lambda: build(rest), lambda: validate([]),
                                                        lambda: promote([])]  # fmt: skip
    for step in steps:
        if step():
            print("stopped: the shipped snapshot is unchanged")
            return 1
    return 0


STEPS = {"status": status, "fetch": fetch, "build": build, "validate": validate, "promote": promote,
         "all": all_steps, "check": check}  # fmt: skip


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in STEPS:
        print(__doc__)
        sys.exit(2)
    DIR.mkdir(parents=True, exist_ok=True)
    sys.exit(STEPS[sys.argv[1]](sys.argv[2:]))


if __name__ == "__main__":
    main()
