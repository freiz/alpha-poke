"""Canonical export and legality of Showdown-format teams, with the local Showdown checkout
(one node process for any number of teams; ``showdown.js``)."""

import json
import re
import subprocess
from pathlib import Path

from alpha_poke.teams import ROOT

SIM = ROOT / "vendor" / "pokemon-showdown" / "dist" / "sim"
HELPER = Path(__file__).with_name("showdown.js")

# team preview hides these formes (Showdown data/rulesets.ts, Team Preview; gen9ou has no
# Species Reveal Clause); replay team keys use the preview names
_PREVIEW_ALWAYS = re.compile(r"(Zacian|Zamazenta)(?!-Crowned)")
_PREVIEW_HIDDEN = re.compile(
    r"(Greninja|Gourgeist|Pumpkaboo|Xerneas|Silvally|Urshifu|Dudunsparce)(-[a-zA-Z?-]+)?"
)


def preview_name(species: str) -> str:
    """The species as team preview shows it (e.g. 'Zamazenta' -> 'Zamazenta-*')."""
    return _PREVIEW_HIDDEN.sub(r"\1-*", _PREVIEW_ALWAYS.sub(r"\1-*", species))


def team_key(species: list[str]) -> str:
    """The team key of the replay tables (``analysis.tables``): sorted preview names."""
    return "|".join(sorted(preview_name(s) for s in species))


def check(texts: list[str], fmt: str = "gen9ou") -> list[dict]:
    """For each Showdown export: {"n": sets parsed, "species": [...], "text": canonical
    export, "problems": validator messages (empty = legal in ``fmt`` today)}."""
    if not texts:
        return []
    stdin = "".join(json.dumps({"id": i, "text": t}) + "\n" for i, t in enumerate(texts))
    r = subprocess.run(
        ["node", str(HELPER), str(SIM), fmt],
        input=stdin, capture_output=True, text=True, check=True, timeout=3600,
    )  # fmt: skip
    out = {}
    for line in r.stdout.splitlines():
        d = json.loads(line)
        out[d.pop("id")] = d
    return [out[i] for i in range(len(texts))]


_BANNED_JS = """
const {Dex} = require(process.argv[1]);
const fmt = Dex.formats.get(process.argv[2]);
const rules = Dex.formats.getRuleTable(fmt);
const out = {};
for (const name of JSON.parse(require('fs').readFileSync(0, 'utf8'))) {
  const s = Dex.forFormat(fmt).species.get(name.replace(/-\\*$/, ''));
  out[name] = !s.exists ? 'unknown' : rules.isBannedSpecies(s) ? `banned (${s.tier})`
    : s.isNonstandard ? `not in the game (${s.isNonstandard})` : '';
}
console.log(JSON.stringify(out));
"""


def banned_species(names: list[str], fmt: str = "gen9ou") -> dict[str, str]:
    """Species (names, preview "-*" forms too) not allowed in ``fmt`` today by the local Showdown
    checkout's rules (its tiers, the format's bans, past or unreleased): name -> why."""
    r = subprocess.run(
        ["node", "-e", _BANNED_JS, str(SIM), fmt],
        input=json.dumps(sorted(set(names))), capture_output=True, text=True, check=True, timeout=600,
    )  # fmt: skip
    return {k: v for k, v in json.loads(r.stdout).items() if v}
