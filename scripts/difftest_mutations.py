"""Mutation checks of the differential tests (doc/difftest.md): each fix undone in turn, the fast
tier must report a regression -- a fix no test notices undone is a fix nothing guards (2026-10-24:
the first Endure scenario never made its Endure hold on; reverting S152 went unseen).

  uv run python scripts/difftest_mutations.py            # the Python fixes
  uv run python scripts/difftest_mutations.py --rust     # the engine / search ones (rebuilds)

Each mutation: (name, file, the fixed text, the text it undoes it to). The file is restored after
each run, whatever happens."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MUTATIONS = [
    ("S152 an Endure's hit keeps the lock", "src/alpha_poke/agents/timers.py",
     'in PROTECTS - {"endure"}:', "in PROTECTS:"),
    ("S153 a Slow Start begun mid-turn counts at once", "src/alpha_poke/agents/timers.py",
     "st.slowstart = [5, not st.switched_now]", "st.slowstart = [5, False]"),
    ("R3 a mon's own weight after its transform", "src/alpha_poke/agents/pokeview.py",
     '    entry = GEN.pokedex.get(to_id(mon.species))\n    if entry and entry.get("weightkg"):\n        return float(entry["weightkg"])\n    return float(mon.weight or 0.0)',
     '    if mon.transformed:\n        entry = GEN.pokedex.get(to_id(mon.species))\n        if entry and entry.get("weightkg"):\n            return float(entry["weightkg"])\n    return float(mon.weight or 0.0)'),
    ("R3 a forme change's weight", "src/alpha_poke/agents/engine_state.py",
     "out[j] = _with(p, id=f, weight_kg=float(w) if w else p.weight_kg)", "out[j] = _with(p, id=f)"),
    ("R4 the Klutz check as the effect began", "src/alpha_poke/agents/engine_state.py",
     'if then == "klutz" and key not in tm.set_gas:\n            return ""', 'if False:\n            return ""'),
    ("R4' Neutralizing Gas held the Klutz off", "src/alpha_poke/agents/engine_state.py",
     'if then == "klutz" and key not in tm.set_gas:', 'if then == "klutz":'),
    ("a transformed active's weight its target's forme's", "src/alpha_poke/agents/engine_state.py",
     "        our_mons[our_active_idx] = _with(our_mons[our_active_idx], weight_kg=copied_weight(tm_us, their_mons[our_t]))",
     "        pass"),
    ("a transform's weight its target's forme's then", "src/alpha_poke/agents/engine_state.py",
     "        w = (GEN.pokedex.get(tm.copied_forme) or {}).get(\"weightkg\") if tm.copied_forme else None",
     "        w = None"),
    ("a copied move's PP before its first use", "src/alpha_poke/agents/pokeview.py",
     '    return min(5, int((GEN.moves.get(mid) or {}).get("pp") or 5))', "    return 5"),
    ("a speed observation's item then", "src/alpha_poke/agents/speed.py",
     "    it = o.item_then if o.item_then is not None else item", "    it = item"),
    ("R2' each hit's item then", "src/alpha_poke/agents/damage_obs.py",
     "    if hit.item_then is not None:  # the item it held at the hit",
     "    if False:  # the item it held at the hit"),
    ("L237 past the turn's end the failure is the next turn's", "src/alpha_poke/agents/engine_state.py",
     "        if now if tm.upkept else last:", "        if last:"),
    ("B2 a status the HP field cured", "src/alpha_poke/agents/speed.py",
     'elif tag in ("-damage", "-heal", "-sethp") and len(p) > 3 and "fnt" not in p[3]:', "elif False:"),
    ("B2 an Encored second mover left out", "src/alpha_poke/agents/speed.py",
     'if any(len(p) > 3 and p[1] == "-start" and p[2][:2] == second and "Encore" in p[3]',
     'if False and any(len(p) > 3 and p[1] == "-start" and p[2][:2] == second and "Encore" in p[3]'),
    ("B2 Mycelium Might / Stall left out", "src/alpha_poke/agents/speed.py",
     'if "stall" in abils or "myceliummight" in abils and _status_move(move):', "if False:"),
    ("B2 our speed with our item then", "src/alpha_poke/agents/speed.py",
     'o = dataclasses.replace(o, ours=o.ours_raw * (1.5 if item == "choicescarf" else 1.0))', "o = o"),
    ("B2 a transformed active left out", "src/alpha_poke/agents/speed.py",
     'if snap["transformed"] or snap["disguised"]:', 'if snap["disguised"]:'),
    ("B2 a possible Illusion left out", "src/alpha_poke/agents/speed.py",
     'if snap["transformed"] or snap["disguised"]:', 'if snap["transformed"]:'),
    ("B2 the opponent's forme then", "src/alpha_poke/agents/speed.py",
     "stat = stat_of(o.base_spe) if stat_of is not None and o.base_spe is not None else speed_stat",
     "stat = speed_stat"),
    ("B3 a Pain Split's HP", "src/alpha_poke/agents/damage_obs.py",
     'elif tag in ("-damage", "-heal", "-sethp") and len(f) > 3:', 'elif tag in ("-damage", "-heal") and len(f) > 3:'),
    ("B3 a transformed mon's hits left out", "src/alpha_poke/agents/damage_obs.py",
     "if att in transformed or dfn in transformed:", "if False:"),
    ("B3 a possible Illusion's hits left out", "src/alpha_poke/agents/damage_obs.py",
     "if illusion.ambiguous.get(att) or illusion.ambiguous.get(dfn):", "if False:"),
    ("B3 another forme's hits left out", "src/alpha_poke/agents/damage_obs.py",
     "or h.forme == forme.get((their, h.defender if h.by_us else h.attacker), h.forme)]", "or True]"),
    ("S156 the types a tera'd mon kept", "src/alpha_poke/agents/engine_state.py",
     "            mons[i] = _with(p, types=tuple(p.base_types))", "            pass"),
    ("B4 the archetypes' item / tera mixed with the base marginal", "src/alpha_poke/agents/engine_state.py",
     "ARCH_MIX = 0.6\n", "ARCH_MIX = 0.0\n"),
    ("S156 ??? is typeless", "src/alpha_poke/agents/engine_state.py",
     '"typeless" if t.name == "THREE_QUESTION_MARKS" else t.name.lower()', "t.name.lower()"),
    ("B5 a taker's [of] lost its item", "src/alpha_poke/agents/damage_obs.py",
     "if lost and of[:2] != f[2][:2]:", "if False:"),
    ("B5 each hit's ability then", "src/alpha_poke/agents/damage_obs.py",
     "    if hit.ability_then is not None:  # and the ability it had then", "    if False:  # and the ability it had then"),
    ("B5 the candidates' ability the one it started with", "src/alpha_poke/agents/damage_obs.py",
     "    if ab is not False and ab is not None:\n        abilities = [(ab, 1.0)]\n    else:\n"
     "        abilities = list((ability_probs(mon) if ab is False else species_ability_probs(mon)).items()) \\\n",
     "    if False:\n        abilities = [(ab, 1.0)]\n    else:\n"
     "        abilities = list(ability_probs(mon).items()) \\\n"),
    ("B5 Skill Swap's abilities", "src/alpha_poke/agents/damage_obs.py",
     'if other and a and b and not b.startswith("[of]"):', "if False:"),
    ("B5 Mummy's / Lingering Aroma's ability (F1)", "src/alpha_poke/agents/damage_obs.py",
     'elif tag == "-activate" and f[3] in ("ability: Mummy", "ability: Lingering Aroma") and len(f) > 4:',
     "elif False:"),
    ("B5 the speed's opponent ability then", "src/alpha_poke/agents/speed.py",
     'opp_abils = {snap["opp_ab"]} if snap["opp_ab"] is not None else abilities(them)', "opp_abils = abilities(them)"),
    ("B5 the speed's own ability then", "src/alpha_poke/agents/speed.py",
     '        if snap["our_ab"] is not None:\n            ability = snap["our_ab"]\n        elif',
     '        if False:\n            ability = snap["our_ab"]\n        elif False and'),
    ("B5 Mummy's / Lingering Aroma's ability (the state)", "src/alpha_poke/agents/timers.py",
     'elif tag == "-activate" and len(p) > 4 and p[3] in ("ability: Mummy", "ability: Lingering Aroma"):',
     "elif False:"),
    ("B5 a Role Play's [of] keeps its ability", "src/alpha_poke/agents/timers.py",
     'if of is not None and tag == "-activate" else None', "if of is not None else None"),
    # (B6's fallback prior: the floor under it keeps the support whole -- the support check cannot
    # tell; tests/test_sample_set.py's test_a_species_ou_never_uses_has_a_prior guards it)
    ("B6 the floor under the base", "src/alpha_poke/agents/engine_state.py", "FLOOR = 1e-3\n", "FLOOR = 0.0\n"),
    # (the belief check's move support is the sampler's own weights: a floor broken there is seen --
    # 2026-10-25 review, the check re-derived it)
    ("B6 the moves' floor", "src/alpha_poke/agents/engine_state.py",
     "    rest = [m for m in legal_moves(species) if weights.get(m, 0.0) <= 0]", "    rest = []"),
    # (its floor under a 0 weight: the full corpus' 10 cases, none in the fast one -- guarded by
    # tests/test_sample_set.py's test_the_move_floor_lifts_a_0_weight)
]
RUST = [
    ("R1 the tree's move used: its own span", "rust/alpha_search/src/ismcts.rs",
     "let used = instructions[from..to.max(from)]", "let used = instructions[..acted.unwrap_or(instructions.len())]"),
    ("R5' the last move always tracked", "rust/patches/poke-engine-0.0.48/src/genx/state.rs",
     "        self.use_last_used_move = true;\n    }\n\n    pub fn set_conditional_mechanics",
     "    }\n\n    pub fn set_conditional_mechanics"),
    ("L234 an ignored item extends nothing", "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
     "let item = if super::items::holder_item_ignored(state, holder) {", "let item = if false {"),
    ("L234 Light Clay: an ignored one", "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
     "&& !super::items::holder_item_ignored(state, attacking_side_reference)", "&& !super::items::item_ignored(state)"),
    ("L235 a status move ignores type immunity", "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
     "            != MoveCategory::Status\n            || choice.move_id == Choices::THUNDERWAVE)",
     "            != MoveCategory::Status\n            || true)"),
    ("L238 no Sleep Clause Mod by default", "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
     "pub static SLEEP_CLAUSE_MOD: AtomicBool = AtomicBool::new(false);",
     "pub static SLEEP_CLAUSE_MOD: AtomicBool = AtomicBool::new(true);"),
    ("L237 this turn's failure is the next turn's", "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
     "        if failed && !last {", "        if false {"),
    ("L237 a status move that did nothing failed", "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
     "&& (choice.tryhit_failed || did_nothing(state, choice, &attacking_side, &instructions))",
     "&& choice.tryhit_failed"),
    ("B3 Stakeout on a switch-in", "rust/alpha_search/src/lib.rs",
     "    if defender_came_in {\n        splash.category", "    if false {\n        splash.category"),
    ("L236 Sheer Force: no status move", "rust/patches/poke-engine-0.0.48/src/genx/abilities.rs",
     "        == MoveCategory::Status\n    {\n        return false;\n    }\n    let volatile",
     "        == MoveCategory::Status\n        && false\n    {\n        return false;\n    }\n    let volatile"),
]


def _fast() -> list[str]:
    r = subprocess.run([sys.executable, "scripts/difftest.py", "--corpus", "fast", "--procs", "14", "--show", "0",
                        "--out", "/dev/null"], cwd=ROOT, capture_output=True, text=True)  # fmt: skip
    return [x for x in r.stdout.splitlines() if x.startswith("REGRESSION")]


def _build() -> None:
    # (--refresh-package too: uv keys its built wheels by the sources' times -- a restored file
    # kept its old time and uv put the mutated build back, 2026-10-24: pytest 198 failures after)
    subprocess.run(["uv", "sync", "--all-groups", "--reinstall-package", "alpha-search", "--reinstall-package",
                    "poke-engine", "--refresh-package", "alpha-search", "--refresh-package", "poke-engine"],
                   cwd=ROOT, check=True, capture_output=True)  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rust", action="store_true")
    a = ap.parse_args()
    # (the code as it is must pass first: against a stale baseline -- a new scenario's own findings
    # not in it -- every mutation reads as caught; 2026-10-24)
    stale = _fast()
    if stale:
        print("the baseline is stale -- the unmutated code regresses; update it first:", stale[:3])
        return 2
    missed = []
    for name, f, fixed, undone in (RUST if a.rust else MUTATIONS):
        p = ROOT / f
        keep = p.with_suffix(p.suffix + ".mutkeep")
        shutil.copy2(p, keep)
        try:
            text = p.read_text()
            if text.count(fixed) != 1:
                print(f"?? {name}: the fixed text is not in {f} once")
                missed.append(name)
                continue
            p.write_text(text.replace(fixed, undone))
            if f.startswith("rust/"):
                _build()
            grown = _fast()
            print(("caught " if grown else "MISSED ") + name + (f"  ({grown[0]}, ...)" if grown else ""))
            if not grown:
                missed.append(name)
        finally:
            shutil.copy(keep, p)  # (a new time: the restore is a change to the build tools too)
            keep.unlink()
            if f.startswith("rust/"):
                _build()
    if a.rust:  # (the build back as the sources are: the Spite test that needs the fix passes)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_dual_engine.py", "-k", "spite_after_its"],
                           cwd=ROOT, capture_output=True, text=True)  # fmt: skip
        print("restored build:", "ok" if r.returncode == 0 else "STALE -- rebuild by hand")
    print(f"{len(missed)} missed: {missed}" if missed else "every mutation caught")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
