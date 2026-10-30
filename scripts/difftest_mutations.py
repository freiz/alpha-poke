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
    (
        "S152 an Endure's hit keeps the lock",
        "src/alpha_poke/agents/timers.py",
        'in PROTECTS - {"endure"}',
        "in PROTECTS",
    ),
    (
        "S153 a Slow Start begun mid-turn counts at once",
        "src/alpha_poke/agents/timers.py",
        "st.slowstart = [5, not st.switched_now]",
        "st.slowstart = [5, False]",
    ),
    (
        "R3 a mon's own weight after its transform",
        "src/alpha_poke/agents/pokeview.py",
        '    entry = GEN.pokedex.get(to_id(mon.species))\n    if entry and entry.get("weightkg"):\n        return float(entry["weightkg"])\n    return float(mon.weight or 0.0)',
        '    if mon.transformed:\n        entry = GEN.pokedex.get(to_id(mon.species))\n        if entry and entry.get("weightkg"):\n            return float(entry["weightkg"])\n    return float(mon.weight or 0.0)',
    ),
    (
        "R3 a forme change's weight",
        "src/alpha_poke/agents/engine_state.py",
        "out[j] = _with(p, id=f, weight_kg=float(w) if w else p.weight_kg)",
        "out[j] = _with(p, id=f)",
    ),
    (
        "R4 the Klutz check as the effect began",
        "src/alpha_poke/agents/engine_state.py",
        'if then == "klutz" and key not in tm.set_gas:\n            return ""',
        'if False:\n            return ""',
    ),
    (
        "R4' Neutralizing Gas held the Klutz off",
        "src/alpha_poke/agents/engine_state.py",
        'if then == "klutz" and key not in tm.set_gas:',
        'if then == "klutz":',
    ),
    (
        "a transformed active's weight its target's forme's",
        "src/alpha_poke/agents/engine_state.py",
        "        our_mons[our_active_idx] = _with(our_mons[our_active_idx], weight_kg=copied_weight(tm_us, their_mons[our_t]),\n",
        "        our_mons[our_active_idx] = _with(our_mons[our_active_idx],\n",
    ),
    (
        "a transform's weight its target's forme's then",
        "src/alpha_poke/agents/engine_state.py",
        '        w = (GEN.pokedex.get(tm.copied_forme) or {}).get("weightkg") if tm.copied_forme else None',
        "        w = None",
    ),
    (
        "a copied move's PP before its first use",
        "src/alpha_poke/agents/pokeview.py",
        '    return min(5, int((GEN.moves.get(mid) or {}).get("pp") or 5))',
        "    return 5",
    ),
    (
        "a speed observation's item then",
        "src/alpha_poke/agents/speed.py",
        "    it = o.item_then if o.item_then is not None else item",
        "    it = item",
    ),
    (
        "R2' each hit's item then",
        "src/alpha_poke/agents/damage_obs.py",
        "    if hit.item_then is not None:\n        cands = [(hit.item_then",
        "    if False:\n        cands = [(hit.item_then",
    ),
    (
        "L237 past the turn's end the failure is the next turn's",
        "src/alpha_poke/agents/engine_state.py",
        "        if now if tm.upkept else last:",
        "        if last:",
    ),
    (
        "B2 a status the HP field cured",
        "src/alpha_poke/agents/speed.py",
        'elif tag in ("-damage", "-heal", "-sethp") and len(p) > 3 and "fnt" not in p[3]:',
        "elif False:",
    ),
    (
        "B2 an Encored second mover left out",
        "src/alpha_poke/agents/speed.py",
        'if any(len(p) > 3 and p[1] == "-start" and p[2][:2] == second and "Encore" in p[3]',
        'if False and any(len(p) > 3 and p[1] == "-start" and p[2][:2] == second and "Encore" in p[3]',
    ),
    (
        "B2 Mycelium Might / Stall left out",
        "src/alpha_poke/agents/speed.py",
        'if "stall" in abils or "myceliummight" in abils and _status_move(move):',
        "if False:",
    ),
    (
        "B2 our speed with our item then",
        "src/alpha_poke/agents/speed.py",
        'o = dataclasses.replace(o, ours=o.ours_raw * (1.5 if item == "choicescarf" else 1.0))',
        "o = o",
    ),
    (
        "B2 a transformed active left out",
        "src/alpha_poke/agents/speed.py",
        'if snap["transformed"] or snap["disguised"]:',
        'if snap["disguised"]:',
    ),
    (
        "B2 a possible Illusion left out",
        "src/alpha_poke/agents/speed.py",
        'if snap["transformed"] or snap["disguised"]:',
        'if snap["transformed"]:',
    ),
    (
        "B2 the opponent's forme then",
        "src/alpha_poke/agents/speed.py",
        "stat = stat_of(o.base_spe) if stat_of is not None and o.base_spe is not None else speed_stat",
        "stat = speed_stat",
    ),
    (
        "B3 a Pain Split's HP",
        "src/alpha_poke/agents/damage_obs.py",
        'elif tag in ("-damage", "-heal", "-sethp") and len(f) > 3:',
        'elif tag in ("-damage", "-heal") and len(f) > 3:',
    ),
    (
        "B3 a transformed mon's hits left out",
        "src/alpha_poke/agents/damage_obs.py",
        "if att in transformed or dfn in transformed:",
        "if False:",
    ),
    (
        "B3 a possible Illusion's hits left out",
        "src/alpha_poke/agents/damage_obs.py",
        "if illusion.ambiguous.get(att) or illusion.ambiguous.get(dfn):",
        "if False:",
    ),
    (
        "B3 another forme's hits left out",
        "src/alpha_poke/agents/damage_obs.py",
        "or h.forme == forme.get((their, h.defender if h.by_us else h.attacker), h.forme)",
        "or True",
    ),
    (
        "S156 the types a tera'd mon kept",
        "src/alpha_poke/agents/engine_state.py",
        "            mons[i] = _with(p, types=tuple(p.base_types))",
        "            pass",
    ),
    (
        "B4 the archetypes' item / tera mixed with the base marginal",
        "src/alpha_poke/agents/engine_state.py",
        "ARCH_MIX = 0.6\n",
        "ARCH_MIX = 0.0\n",
    ),
    (
        "S156 ??? is typeless",
        "src/alpha_poke/agents/engine_state.py",
        '"typeless" if t.name == "THREE_QUESTION_MARKS" else t.name.lower()',
        "t.name.lower()",
    ),
    (
        "B5 a taker's [of] lost its item",
        "src/alpha_poke/agents/damage_obs.py",
        "if lost and of[:2] != f[2][:2]:",
        "if False:",
    ),
    (
        "B5 each hit's ability then",
        "src/alpha_poke/agents/damage_obs.py",
        "    if hit.ability_then is not None:  # and the ability it had then",
        "    if False:  # and the ability it had then",
    ),
    (
        "B5 the candidates' ability the one it started with",
        "src/alpha_poke/agents/damage_obs.py",
        "    if ab is not False and ab is not None:\n        abilities = [(ab, 1.0)]\n    else:\n"
        "        abilities = list((ability_probs(mon) if ab is False else species_ability_probs(mon)).items()) \\\n",
        "    if False:\n        abilities = [(ab, 1.0)]\n    else:\n"
        "        abilities = list(ability_probs(mon).items()) \\\n",
    ),
    (
        "B5 Skill Swap's abilities",
        "src/alpha_poke/agents/damage_obs.py",
        'if other and a and b and not b.startswith("[of]"):',
        "if False:",
    ),
    (
        "B5 Mummy's / Lingering Aroma's ability (F1)",
        "src/alpha_poke/agents/damage_obs.py",
        '            tag == "-activate"\n            and f[3] in ("ability: Mummy", "ability: Lingering Aroma")',
        '            False\n            and f[3] in ("ability: Mummy", "ability: Lingering Aroma")',
    ),
    (
        "B5 the speed's opponent ability then",
        "src/alpha_poke/agents/speed.py",
        'opp_abils = {snap["opp_ab"]} if snap["opp_ab"] is not None else abilities(them)',
        "opp_abils = abilities(them)",
    ),
    (
        "B5 the speed's own ability then",
        "src/alpha_poke/agents/speed.py",
        '        if snap["our_ab"] is not None:\n            ability = snap["our_ab"]\n        elif',
        '        if False:\n            ability = snap["our_ab"]\n        elif False and',
    ),
    # (B5's state copy -- the timers' Mummy / Lingering Aroma -activate: B8 made poke-env set the
    # same current ability, two copies neither alone seen in the differential (2026-10-26, the whole
    # run: MISSED); guarded by test_timers.py's test_a_lingering_aromas_ability_on_the_contact_mon)
    (
        "B5 a Role Play's [of] keeps its ability",
        "src/alpha_poke/agents/timers.py",
        'if of is not None and tag == "-activate" else None',
        "if of is not None else None",
    ),
    (
        "L243 our locked move's real PP",
        "src/alpha_poke/agents/engine_state.py",
        "        if available_moves is not None and mid in available_moves and not (req_pp and mid in req_pp\n",
        "        if available_moves is not None and mid in available_moves and not (False and mid in req_pp\n",
    ),
    (
        "a Sleep Talk's Rollout locks nothing",
        "src/alpha_poke/agents/timers.py",
        'st.rollout_moving = mv in ("rollout", "iceball") and st.status.get(sp) != "slp" and not any(',
        'st.rollout_moving = mv in ("rollout", "iceball") and not any(',
    ),
    # (the belief's own derivation -- the oracle-mode state checks never see it: state_facts does)
    (
        "an ability set over an unknown one: the old its own",
        "src/alpha_poke/agents/poke_env_fixes.py",
        "            mon._ability = old  # (the one it had: its own)",
        "            pass",
    ),
    (
        "S158 the foe's Choice lock (and a replay's own: issue #28)",
        "src/alpha_poke/agents/engine_state.py",
        "        if (\n            last\n            and not tm.item_new",
        "        if (\n            False\n            and not tm.item_new",
    ),
    (
        "S158 a hidden forme",
        "src/alpha_poke/agents/engine_state.py",
        "        id=s.forme or mon.species,",
        "        id=mon.species,",
    ),
    (
        "S158 a hidden forme's types",
        "src/alpha_poke/agents/engine_state.py",
        "            _base_types(s.forme)\n            if s.forme and",
        "            _types(mon)\n            if s.forme and",
    ),
    (
        "S158 a transformed lock's slot order",
        "src/alpha_poke/agents/engine_state.py",
        "            ids = list(req) if len(req) == 4 or not base else base + extra",
        "            ids = list(req) if len(req) == 4 or not base else list(dict.fromkeys(list(req) + base))[:4]",
    ),
    (
        "S158 a Healing Wish waiting",
        "src/alpha_poke/agents/timers.py",
        '            st.healing_wish = 1 if mv == "healingwish" else 2',
        "            pass",
    ),
    (
        "S158 the Toxic Spikes' order",
        "src/alpha_poke/agents/engine_state.py",
        "        toxic_spikes_order=_toxic_spikes_order(sc),\n",
        "",
    ),
    (
        "S158 a Transform copies the times attacked",
        "src/alpha_poke/agents/timers.py",
        "            st.times_attacked[sp] = ost.times_attacked.get(st.copied_from, 0)",
        "            pass",
    ),
    (
        "S158 a Future Sight's hit counts",
        "src/alpha_poke/agents/timers.py",
        "        or st.future_hit\n",
        "        or False\n",
    ),
    (
        "S158 a Stellar type marked as it hits",
        "src/alpha_poke/agents/timers.py",
        '        mover.stellar_moves[mover.just_moved].add(mover.stellar_pending)\n        mover.stellar_pending = ""\n',
        "        pass\n",
    ),
    (
        "S158 Revival Blessing's faints",
        "src/alpha_poke/agents/engine_state.py",
        "        revived_faints=min(tm_us.revivals, 6),",
        "        revived_faints=0,",
    ),
    (
        "S158 the foe's nature and EVs",
        "src/alpha_poke/agents/engine_state.py",
        '        nature=s.nature,\n        **({"evs": tuple(s.evs)} if s.evs else {}),\n',
        "",
    ),
    (
        "S158 our natures and EVs",
        "src/alpha_poke/agents/engine_state.py",
        '        **({"nature": own_set[0], "evs": tuple(own_set[1])} if own_set else {}),\n',
        "",
    ),
    (
        "S158 a copy keeps its nature",
        "src/alpha_poke/agents/engine_state.py",
        '    kept = {"nature": str(p.nature).lower(), "evs": tuple(p.evs)}',
        "    kept = {}",
    ),
    (
        "S158 a transformed mon's own nature",
        "src/alpha_poke/agents/engine_state.py",
        "        nature=str(p.nature).lower(), evs=tuple(p.evs), once_used=p.once_used,",
        "        once_used=p.once_used,",
    ),
    (
        "S158 the stats of the forme it transformed into",
        "src/alpha_poke/agents/engine_state.py",
        "        if not entry or to_id(tm.copied_forme) == _sp_id(target):",
        "        if True:",
    ),
    (
        "S157 a Terapagos's Stellar boosts unmarked",
        "src/alpha_poke/agents/engine_state.py",
        '    stellar_moves = () if to_id(mon.species).startswith("terapagos") else (',
        "    stellar_moves = () if False else (",
    ),
    (
        "L242 our called lock",
        "src/alpha_poke/agents/engine_state.py",
        "        called = keep != lock_move and lock_move in CALLED_LOCKS",
        "        called = False",
    ),
    (
        "L241 our Rollout's lock",
        "src/alpha_poke/agents/timers.py",
        "        if st.rollout_moving and (st.rollout is None or st.rollout[0] != mv):\n            st.rollout = [mv, 0]",
        "        if False:\n            st.rollout = [mv, 0]",
    ),
    # (B6's fallback prior: the floor under it keeps the support whole -- the support check cannot
    # tell; tests/test_sample_set.py's test_a_species_ou_never_uses_has_a_prior guards it)
    (
        "B6 the floor under the base",
        "src/alpha_poke/agents/engine_state.py",
        "FLOOR = 1e-3\n",
        "FLOOR = 0.0\n",
    ),
    # (the belief check's move support is the sampler's own weights: a floor broken there is seen --
    # 2026-10-25 review, the check re-derived it)
    (
        "B6 the moves' floor",
        "src/alpha_poke/agents/engine_state.py",
        "    rest = [m for m in legal_moves(species) if weights.get(m, 0.0) <= 0]",
        "    rest = []",
    ),
    # (its floor under a 0 weight: the full corpus' 10 cases, none in the fast one -- guarded by
    # tests/test_sample_set.py's test_the_move_floor_lifts_a_0_weight)
]
RUST = [
    (
        "L246 Cursed Body at each hit",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "                        Effect::Status(_) | Effect::VolatileStatus(PokemonVolatileStatus::DISABLE)",
        "                        Effect::Status(_)",
    ),
    (
        "L247 a reflected move's miss its reflector's",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "        if choice.reflected && !choice.protected {\n            move_failed(state, &attacking_side_ref.get_other_side(),",
        "        if false {\n            move_failed(state, &attacking_side_ref.get_other_side(),",
    ),
    (
        "L245 no end of the turn after the win",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "    if state.battle_is_over() != 0.0 {\n        return vec![];\n    }",
        "    if false {\n        return vec![];\n    }",
    ),
    (
        "L244 Sleep Talk calls no nosleeptalk / charge move",
        "rust/patches/poke-engine-0.0.48/src/state.rs",
        "            if p.id != Choices::NONE && !p.choice.flags.charge && !NO_SLEEP_TALK.contains(&p.id) {",
        "            if p.id != Choices::SLEEPTALK && p.id != Choices::NONE {",
    ),
    (
        "L243 a locked slot at 0 PP",
        "rust/patches/poke-engine-0.0.48/src/genx/state.rs",
        "            let lock_slot = locked\n",
        "            let lock_slot = false && locked\n",
    ),
    # (L242's called move run on the lock's turn, not its caller again: in the scenarios the battle's
    # last move is the locked one -- a Copycat run anew copies the same; guarded by
    # tests/test_dual_engine.py's test_l242_the_called_move_not_the_battles_last)
    (
        "L242 a called lock keeps its caller's slot",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "    let caller = if own { None } else { side.caller_slot() };",
        "    let caller = if own { None } else { side.caller_slot().filter(|_| false) };",
    ),
    (
        "L241 Rollout's hit counts",
        "rust/patches/poke-engine-0.0.48/src/genx/choice_effects.rs",
        "                        volatile_status: PokemonVolatileStatus::ROLLOUT,\n                        amount: 1,",
        "                        volatile_status: PokemonVolatileStatus::ROLLOUT,\n                        amount: 0,",
    ),
    (
        "L241 Rollout ends without a hit",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "        rollout_end_of_turn(state, side_ref, incoming_instructions);\n",
        "",
    ),
    (
        "L239 an ability's End: its volatile off",
        "rust/patches/poke-engine-0.0.48/src/genx/abilities.rs",
        "    if let Some(v) = volatile {",
        "    if let Some(v) = volatile.filter(|_| false) {",
    ),
    (
        "L240 a move with no target the battle's last move",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "            // (a stopped one, a cant: clearActiveMove(true), none)\n            set_battle_last_move(state, &choice, &mut incoming_instructions);",
        "            // (a stopped one, a cant: clearActiveMove(true), none)",
    ),
    (
        "L241 an Uproar's own lock",
        "rust/patches/poke-engine-0.0.48/src/genx/state.rs",
        "            || self.volatile_statuses.contains(&PokemonVolatileStatus::UPROAR)\n",
        "",
    ),
    (
        "R1 the tree's move used: its own span",
        "rust/alpha_search/src/ismcts.rs",
        "let used = instructions[from..to.max(from)]",
        "let used = instructions[..acted.unwrap_or(instructions.len())]",
    ),
    (
        "R5' the last move always tracked",
        "rust/patches/poke-engine-0.0.48/src/genx/state.rs",
        "        self.use_last_used_move = true;\n    }\n\n    pub fn set_conditional_mechanics",
        "    }\n\n    pub fn set_conditional_mechanics",
    ),
    (
        "L234 an ignored item extends nothing",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "let item = if super::items::holder_item_ignored(state, holder) {",
        "let item = if false {",
    ),
    (
        "L234 Light Clay: an ignored one",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "&& !super::items::holder_item_ignored(state, attacking_side_reference)",
        "&& !super::items::item_ignored(state)",
    ),
    (
        "L235 a status move ignores type immunity",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "            != MoveCategory::Status\n            || choice.move_id == Choices::THUNDERWAVE)",
        "            != MoveCategory::Status\n            || true)",
    ),
    (
        "L238 no Sleep Clause Mod by default",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "pub static SLEEP_CLAUSE_MOD: AtomicBool = AtomicBool::new(false);",
        "pub static SLEEP_CLAUSE_MOD: AtomicBool = AtomicBool::new(true);",
    ),
    (
        "L237 this turn's failure is the next turn's",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "        if failed && !last {",
        "        if false {",
    ),
    (
        "L237 a status move that did nothing failed",
        "rust/patches/poke-engine-0.0.48/src/genx/generate_instructions.rs",
        "&& (choice.tryhit_failed || did_nothing(state, choice, &attacking_side, &instructions))",
        "&& choice.tryhit_failed",
    ),
    (
        "B3 Stakeout on a switch-in",
        "rust/alpha_search/src/lib.rs",
        "    if defender_came_in {\n        splash.category",
        "    if false {\n        splash.category",
    ),
    (
        "L236 Sheer Force: no status move",
        "rust/patches/poke-engine-0.0.48/src/genx/abilities.rs",
        "        == MoveCategory::Status\n    {\n        return false;\n    }\n    let volatile",
        "        == MoveCategory::Status\n        && false\n    {\n        return false;\n    }\n    let volatile",
    ),
]


class RunnerFailed(RuntimeError):
    """The fast tier's runner broke (not a regression: its exit status 0 with none, 1 with
    some -- 2026-10-25 review, a crash read as nothing found)."""


def _fast() -> list[str]:
    r = subprocess.run([sys.executable, "scripts/difftest.py", "--corpus", "fast", "--procs", "14", "--show", "0",
                        "--out", "/dev/null"], cwd=ROOT, capture_output=True, text=True)  # fmt: skip
    grown = [x for x in r.stdout.splitlines() if x.startswith("REGRESSION")]
    if r.returncode not in (0, 1) or (r.returncode == 1) != bool(grown):
        raise RunnerFailed(
            f"exit {r.returncode}: {(r.stderr or r.stdout).strip().splitlines()[-1:]}"
        )
    return grown


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
    try:
        stale = _fast()
    except RunnerFailed as e:
        print("the fast tier's runner broke on the code as it is:", e)
        return 2
    if stale:
        print("the baseline is stale -- the unmutated code regresses; update it first:", stale[:3])
        return 2
    missed = []
    todo = RUST if a.rust else MUTATIONS
    # (2026-10-25: a wrapper set RUST without --rust -- none run, "every mutation caught")
    if not todo:
        print("no mutation to run" + ("" if a.rust else " (the Rust ones need --rust)"))
        return 2
    for name, f, fixed, undone in todo:
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
            try:
                grown = _fast()
            except RunnerFailed as e:  # (a crash is no catch: a finding of the checks is)
                print(f"ERROR {name}: the runner broke -- {e}")
                missed.append(name)
                continue
            # (only the "error" kind grown: the mutated code raised in the checks -- a crash, no
            # catch of theirs; 2026-10-26 review)
            if grown and all(" error " in g for g in grown):
                print(f"ERROR {name}: only the checks' errors grew ({grown[0]}, ...)")
                missed.append(name)
                continue
            print(
                ("caught " if grown else "MISSED ")
                + name
                + (f"  ({grown[0]}, ...)" if grown else "")
            )
            if not grown:
                missed.append(name)
        finally:
            shutil.copy(keep, p)  # (a new time: the restore is a change to the build tools too)
            keep.unlink()
            if f.startswith("rust/"):
                _build()
    # (the code back as it was: the fast tier within its baseline again -- the build too; a
    # failed check exits 3, 2026-10-25 review: it printed STALE and returned 0)
    restored = not _fast()
    if a.rust:  # (and the Spite test that needs the fix passes)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_dual_engine.py", "-k", "spite_after_its"],
                           cwd=ROOT, capture_output=True, text=True)  # fmt: skip
        restored = restored and r.returncode == 0
    print(
        "restored:",
        "ok"
        if restored
        else "STALE -- the code or the build is not back; rebuild / restore by hand",
    )
    print(f"{len(missed)} missed: {missed}" if missed else f"every mutation caught ({len(todo)})")
    return 3 if not restored else 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
