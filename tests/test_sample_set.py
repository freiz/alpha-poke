"""Set sampling (agents/engine_state.sample_set) draws only sets the battle allows: an Assault
Vest holder cannot choose a status move (2026-10-24, plan C's slot check: a replay's
Slowking-Galar with Toxic and Chilly Reception was drawn an Assault Vest -- its Toxic, the move
it used, no option of the training state)."""

import random

from poke_env.battle import Pokemon

from alpha_poke.agents.belief_state import BeliefModel
from alpha_poke.agents.engine_state import KnownSet, _status, sample_set

# (the replay's: gen9ou-2122314865, side one -- its game-wide known moves Toxic, Future Sight,
# Sludge Bomb; without the check, Assault Vest about one draw in a few hundred)
NAMES = ("Kyurem", "Slowking-Galar", "Great Tusk", "Kingambit", "Iron Valiant", "Dragapult")
KNOWN = KnownSet(moves=["toxic", "futuresight", "sludgebomb"])


def _mon(*moves: str, item: str | None = None) -> Pokemon:
    mon = Pokemon(species="slowkinggalar", gen=9)
    for m in moves:
        mon._add_move(m)
    if item is not None:
        mon.item = item
    return mon


def test_a_mon_with_a_status_move_draws_no_assault_vest():
    belief = BeliefModel.load()
    rng = random.Random(0)
    items = [sample_set(belief, _mon(), NAMES, rng, known=KNOWN).item for _ in range(3000)]
    assert "assaultvest" not in items
    # (the check means something: without a status move known it is drawn)
    rng = random.Random(0)
    items = [sample_set(belief, _mon("sludgebomb"), NAMES, rng).item for _ in range(300)]
    assert "assaultvest" in items


def test_an_assault_vest_holder_draws_no_status_move():
    belief = BeliefModel.load()
    rng = random.Random(0)
    for _ in range(200):
        s = sample_set(belief, _mon("sludgebomb", item="assaultvest"), NAMES, rng)
        assert s.item == "assaultvest"
        assert not any(_status(m) for m in s.moves), s.moves


def test_an_item_replays_never_show_is_drawn():
    """2026-10-25 (the belief check's prior support): the archetypes are mined from replays, which
    show an item only when it reveals itself -- a Latias's Soul Dew never: its archetypes had no
    weight on it, the sampler never drew it (Smogon's usage: 36%). Mixed with the base marginal
    (ARCH_MIX) it is drawn far more often than at mix 0, the old belief (on the full replay data:
    never; on the tests' 5,000-game sample Latias has no archetypes of its own, so the old
    belief draws it a little)."""
    belief = BeliefModel.load()
    names = ("Corviknight", "Great Tusk", "Latias", "Gholdengo", "Kingambit", "Dragapult")
    mon = Pokemon(species="latias", gen=9)

    def soul_dews(mix):
        rng = random.Random(0)
        draws = (sample_set(belief, mon, names, rng, 1.0, mix=mix).item for _ in range(400))
        return sum(item == "souldew" for item in draws)

    assert soul_dews(None) > 3 * soul_dews(0.0)


def test_a_cosmetic_formes_prior_is_its_base_species():
    """Smogon's usage lists Maushold-Four under Maushold: its prior was empty (2026-10-25). Only
    a forme the same in battle falls back -- not Tauros-Paldea-Combat to Tauros."""
    from alpha_poke.belief.priors import SmogonPrior

    belief = BeliefModel.load()
    p = belief.prior
    while not isinstance(p, SmogonPrior):
        p = p.base
    assert p.predict("Maushold-Four", ()).move == p.predict("Maushold", ()).move != {}
    assert p.predict("Tauros-Paldea-Combat", ()).move != p.predict("Tauros", ()).move


def test_a_species_ou_never_uses_has_a_prior():
    """2026-10-25 (the belief check: 91% of its prior gaps): a species not in OU's usage had an
    empty prior -- no move but the revealed ones, no item. Its fallback: Showdown's random-battle
    movepool and tera types, OU's items across species; a species not there either, its learnset."""
    from alpha_poke.belief.priors import SmogonPrior, legal_moves

    belief = BeliefModel.load()
    p = belief.prior
    while not isinstance(p, SmogonPrior):
        p = p.base
    glalie = p.predict("Glalie", ())
    assert set(glalie.move) == {"earthquake", "freezedry", "spikes", "taunt"}
    assert (
        set(glalie.tera) == {"ghost", "ground", "water"}
        and glalie.item.get("heavydutyboots", 0) > 0.1
    )
    assert "spore" in legal_moves("smeargle") and "spikes" in legal_moves("glalie")


def test_a_legal_set_no_ou_player_uses_is_never_impossible():
    """The floor (engine_state.FLOOR): a move of its learnset no archetype has, an item OU uses
    elsewhere, any tera type, a forme's item for sure -- reachable, not drawn in practice."""
    from alpha_poke.agents.engine_state import FLOOR, _move_floor, base_marginal, required_item

    belief = BeliefModel.load()
    names = ("Corviknight", "Great Tusk", "Latias", "Gholdengo", "Kingambit", "Dragapult")
    w = _move_floor({"bravebird": 1.0, "roost": 1.0}, "corviknight")
    assert w["bodypress"] > 0 and abs(sum(w.values()) - 2.0 * (1 + FLOOR)) < 1e-9
    items = base_marginal(belief, "Corviknight", names, "item")
    assert items.get("choicespecs", 0) > 0 and abs(sum(items.values()) - 1) < 1e-9
    assert base_marginal(belief, "Corviknight", names, "tera").get("stellar", 0) > 0
    assert "lustrousorb" in base_marginal(belief, "Palkia", (), "item")
    assert required_item(Pokemon(species="zamazentacrowned", gen=9)) == "rustedshield"
    # (mix 0, the old belief: the team prior's alone, no floor)
    from alpha_poke.agents.engine_state import _prior
    from alpha_poke.analysis.roles import to_id

    old = base_marginal(belief, "Corviknight", names, "item", mix=0.0)
    assert set(old) == {to_id(k) for k in _prior(belief, "Corviknight", names).item}


def test_the_fallback_is_off_at_mix_0():
    """2026-10-25 review: ALPHA_ARCH_MIX=0 (the search A/B's old belief) left the fallback prior
    on -- not the belief before it for a species OU's usage lacks."""
    from alpha_poke.agents.engine_state import _prior, base_marginal

    belief = BeliefModel.load()
    assert _prior(belief, "Glalie", ("Glalie",), mix=0).move == {}
    assert _prior(belief, "Glalie", ("Glalie",)).move  # (on by default)
    assert base_marginal(belief, "Glalie", ("Glalie",), "item", 0.0) == {}


def test_a_species_gets_only_the_items_it_can_use():
    """2026-10-25 review: OU's items across species gave any fallback species a Booster Energy (7%)
    and an Ogerpon's mask (4%): another species' own item, Booster Energy without its abilities."""
    from alpha_poke.agents.engine_state import _smogon
    from alpha_poke.belief.priors import items_for

    g = _smogon(BeliefModel.load()).global_item
    for sid, gets, never in (("glalie", "leftovers", ("boosterenergy", "wellspringmask", "souldew")),
                             ("ironvaliant", "boosterenergy", ("wellspringmask",)),
                             ("ogerponwellspring", "wellspringmask", ("boosterenergy",))):  # fmt: skip
        f = items_for(sid, g)
        assert f.get(gets, 0) > 0 and not any(f.get(i, 0) for i in never), (sid, gets)
        assert abs(sum(f.values()) - 1) < 1e-9


def test_an_arceus_formes_plate_is_its_item():
    """Showdown's requiredItems (plural) for an Arceus forme: its Gen 9 one, the Plate (the
    Z-Crystal is non-standard) -- required_item read requiredItem only (2026-10-25 review)."""
    from types import SimpleNamespace

    from alpha_poke.agents.engine_state import required_item

    assert required_item(SimpleNamespace(species="arceusfire")) == "flameplate"
    assert required_item(SimpleNamespace(species="arceus")) is None


def test_the_move_floor_lifts_a_0_weight():
    """An archetype lists its species' moves, many at 0: the floor passed over a move with a weight
    (any), so those stayed impossible (2026-10-25, the belief check on the sampler's own weights)."""
    from alpha_poke.agents.engine_state import _move_floor

    out = _move_floor({"spikes": 1.0, "freezedry": 0.0}, "glalie")
    assert out["freezedry"] > 0 and out["earthquake"] > 0 and out["spikes"] == 1.0


def test_our_natures_and_evs_from_our_team():
    """S158: no request names our natures or EVs -- the engine needs them (a forme change's stats,
    a confusion berry): from our team (text, or a poke-env teambuilder), by species and nickname
    (a transformed mon's poke-env species is its target's)."""
    from types import SimpleNamespace

    from poke_env.teambuilder import ConstantTeambuilder

    from alpha_poke.agents.knowledge_player import remember_own_sets

    text = "Bob (Ditto) @ Choice Scarf\nAbility: Imposter\nEVs: 252 HP / 4 Def / 252 Spe\nRelaxed Nature\n- Transform\n"
    for team in (text, ConstantTeambuilder(text)):
        b = SimpleNamespace()
        remember_own_sets(b, team)
        assert b._alpha_own_sets["ditto"] == ("relaxed", (252, 0, 4, 0, 0, 252))
        assert b._alpha_own_sets["bob"] == b._alpha_own_sets["ditto"]


def test_a_hidden_formes_set_makes_its_forme():
    """S158: the team preview hides some formes (Showdown's onTeamPreview: Zacian-*, Urshifu-*,
    Greninja-* ...; a Greninja-Bond shows as Greninja even when it comes in) -- the engine needs
    them: Battle Bond works only as Greninja-Bond, a Rusted Sword Zacian is Zacian-Crowned."""
    from alpha_poke.agents.engine_state import resolve_forme

    assert (
        resolve_forme("greninja", "lifeorb", "battlebond", ["hydropump", "darkpulse"])
        == "greninjabond"
    )
    assert resolve_forme("greninja", "lifeorb", "protean", ["hydropump", "darkpulse"]) == "greninja"
    assert resolve_forme("zacian", "rustedsword", "intrepidsword", ["playrough"]) == "zaciancrowned"
    assert resolve_forme("zacian", "lifeorb", "intrepidsword", ["playrough"]) == "zacian"
    assert (
        resolve_forme("urshifu", "choiceband", "unseenfist", ["surgingstrikes", "uturn"])
        == "urshifurapidstrike"
    )
    assert (
        resolve_forme("urshifu", "choiceband", "unseenfist", ["wickedblow", "uturn"]) == "urshifu"
    )


def test_a_hidden_formes_changed_types_kept():
    """A hidden forme's types its own (Zacian-Crowned's Steel) -- unless they changed: a Protean
    Greninja's after its Ice Beam (the full belief check: our state gave it Water / Dark again,
    the Ice Beam's damage no STAB, the true set ruled out)."""
    from poke_env.battle import PokemonType

    from alpha_poke.agents.engine_state import SampledSet, _their_mon

    s = SampledSet(moves=["icebeam"], item="choicespecs", ability="battlebond", tera="water",
                   stats={"hp": 285, "atk": 203, "def": 171, "spa": 305, "spd": 178, "spe": 377},
                   forme="greninjabond")  # fmt: skip
    mon = Pokemon(species="greninja", gen=9)
    assert {str(t).lower() for t in _their_mon(mon, s).types} == {"water", "dark"}
    mon._temporary_types = [PokemonType.ICE]
    assert str(_their_mon(mon, s).types[0]).lower() == "ice"
    zacian = SampledSet(moves=["playrough"], item="rustedsword", ability="intrepidsword", tera="fairy",
                        stats={"hp": 323, "atk": 337, "def": 266, "spa": 176, "spd": 266, "spe": 390},
                        forme="zaciancrowned")  # fmt: skip
    assert {str(t).lower() for t in _their_mon(Pokemon(species="zacian", gen=9), zacian).types} == {
        "fairy",
        "steel",
    }


def test_a_revealed_greninja_bond_stays_greninja_bond():
    """2026-10-26 review: a switched-in Greninja-Bond (its set's forme, resolve_forme) went back to
    Greninja in _formes -- the shown species "Greninja" read as its forme now -- Battle Bond inert.
    (The state checks alias the two names: SAME_SPECIES hid it.)"""
    import poke_engine as pe

    from alpha_poke.agents.engine_state import _formes
    from alpha_poke.agents.timers import SideTimers

    mon = Pokemon(species="greninja", gen=9)
    tm = SideTimers()
    tm.names["Greninja"] = "greninja"
    built = [pe.Pokemon(id="greninjabond", ability="battlebond")]
    assert str(_formes({"p2: Greninja": mon}, [mon], built, tm)[0].id).lower() == "greninjabond"
    plain = [pe.Pokemon(id="greninja", ability="protean")]
    assert str(_formes({"p2: Greninja": mon}, [mon], plain, tm)[0].id).lower() == "greninja"


def test_a_seen_base_forme_is_no_hidden_forme():
    """2026-10-26 review: resolve_forme ran on a mon whose switch-in showed it -- an "Urshifu" seen
    with a Surging Strikes drawn was built as Rapid Strike (types, stats). Only one never in, and
    Greninja (Greninja-Bond shows as Greninja)."""
    belief = BeliefModel.load()
    known = KnownSet(moves=["surgingstrikes"])
    unseen = Pokemon(species="urshifu", gen=9)
    assert (
        sample_set(belief, unseen, ("Urshifu",), random.Random(0), known=known).forme
        == "urshifurapidstrike"
    )
    seen = Pokemon(species="urshifu", gen=9)
    seen._revealed = True  # (it came in as "Urshifu": Single Strike)
    assert sample_set(belief, seen, ("Urshifu",), random.Random(0), known=known).forme is None


def test_raked_items_match_the_usage():
    """2026-10-31 (issue #33): the archetypes and the team prior count the items replays show, so
    the drawn items lean to the self-revealing ones. With the belief's ``rake`` on, a species'
    items drawn with nothing revealed follow Smogon's usage (the teams' own items, RAKE_CUTOFF); off, they do
    not -- and an item the usage lacks stays possible (the floor)."""
    from alpha_poke.agents.engine_state import _rake_usage, rake_factors
    from alpha_poke.analysis.roles import to_id

    belief = BeliefModel.load()
    name = "Dragapult"
    usage = _rake_usage(belief).predict(name, (name,)).item
    t = sum(usage.values())
    usage = {("none" if to_id(k) == "nothing" else to_id(k)): v / t for k, v in usage.items()}

    def drawn(rake: bool) -> dict:
        belief.rake = rake
        rng = random.Random(0)
        n = 4000
        counts: dict = {}
        for _ in range(n):
            it = sample_set(belief, Pokemon(species="dragapult", gen=9), (name,), rng).item
            counts[it] = counts.get(it, 0) + 1
        return {k: v / n for k, v in counts.items()}

    def tv(d: dict) -> float:
        return sum(abs(d.get(k, 0.0) - usage.get(k, 0.0)) for k in set(d) | set(usage)) / 2

    try:
        off, on = drawn(False), drawn(True)
        assert tv(on) < 0.06, tv(on)
        assert tv(off) > tv(on) + 0.05, (tv(off), tv(on))
        c = rake_factors(belief, name, "item")
        assert c and all(v > 0 for v in c.values())  # (nothing the draw made is ruled out)
    finally:
        belief.rake = False


def test_evidence_items_are_the_damage_and_speed_ones():
    from alpha_poke.belief.priors import evidence_items

    ev = evidence_items()
    for item in ("choicespecs", "choiceband", "choicescarf", "lifeorb", "expertbelt", "assaultvest",
                 "eviolite", "occaberry", "dracoplate", "mysticwater", "normalgem"):  # fmt: skip
        assert item in ev, item
    for item in ("leftovers", "heavydutyboots", "rockyhelmet", "covertcloak", "sitrusberry"):
        assert item not in ev, item


def test_f1_other_draws_an_item_its_candidates_do_not_list():
    """2026-10-31 (issue #33): once a clean hit is seen, F1's candidates are the only items drawn;
    the TOP_ITEMS cut left 3-4% of true items (Rocky Helmet, Leftovers, ...) never drawn again.
    With the belief's ``f1_all``: OTHER stands for the rest, an item among them drawn after."""
    from alpha_poke.agents.damage_obs import OTHER, TOP_ITEMS, _candidates
    from alpha_poke.agents.speed import spread_dist

    belief = BeliefModel.load()
    names = ("Dragapult", "Great Tusk", "Kingambit", "Gholdengo", "Corviknight", "Primarina")
    mon = Pokemon(species="dragapult", gen=9)
    try:
        belief.f1_all = False
        plain = {c[0] for c in _candidates(belief, mon, names)[0]}
        assert len(plain) <= TOP_ITEMS and OTHER not in plain
        belief.f1_all = True
        cands = {c[0] for c in _candidates(belief, mon, names)[0]}
        assert OTHER in cands and plain < cands
        listed = cands - {OTHER}
        spread = spread_dist("dragapult")[0][0]
        # (the posterior over every candidate, as damage_posteriors gives it: Specs and the rest)
        post = [(c, "infiltrator", spread, 1.0 if c in ("choicespecs", OTHER) else 0.0)
                for c in sorted(cands)]  # fmt: skip
        rng = random.Random(0)
        items = [sample_set(belief, mon, names, rng, dmg_post=post).item for _ in range(400)]
        assert "choicespecs" in items and OTHER not in items and "other" not in items
        others = [i for i in items if i != "choicespecs"]
        assert others and not set(others) & listed, set(others) & listed
    finally:
        belief.f1_all = False


def test_stratified_worlds_cover_every_likely_item():
    """2026-10-31 (issue #33): a decision's W worlds drawn apart miss a value of probability P
    with (1 - P) ** W (37% at 1 / W); at Latin-hypercube quantiles each mon's item covers every
    value of P >= 1 / W, and over many decisions the items keep their marginal."""
    from alpha_poke.agents.engine_state import item_marginal

    belief = BeliefModel.load()
    names = ("Dragapult", "Great Tusk", "Kingambit", "Gholdengo", "Corviknight", "Primarina")
    mon = Pokemon(species="dragapult", gen=9)
    ss = belief.sets.get("Dragapult")
    marg, _ = item_marginal(belief, ss, "Dragapult", names, ss.posterior())
    likely = {i for i, p in marg.items() if p >= 1 / 32}
    rng = random.Random(0)
    counts: dict = {}
    for _ in range(60):  # (decisions)
        off = rng.random()
        perm = list(range(32))
        rng.shuffle(perm)
        drawn = [
            sample_set(belief, mon, names, rng, u=(perm[j] + off) / 32).item for j in range(32)
        ]
        assert likely <= set(drawn), likely - set(drawn)
        for i in drawn:
            counts[i] = counts.get(i, 0) + 1
    n = sum(counts.values())
    tv = sum(abs(counts.get(i, 0) / n - marg.get(i, 0)) for i in set(counts) | set(marg)) / 2
    assert tv < 0.03, tv


def test_build_worlds_is_the_plain_loop_unless_stratified(monkeypatch):
    import alpha_poke.agents.engine_state as es

    calls = []
    monkeypatch.setattr(es, "build_state", lambda *a, **kw: calls.append(kw) or a[3].random())
    belief = BeliefModel.load()
    plain = es.build_worlds(None, belief, (), random.Random(1), 4, move_beta=2.0)
    assert plain == [random.Random(1).random() for _ in range(1)] + plain[1:]
    r = random.Random(1)
    assert plain == [r.random() for _ in range(4)]  # (the same draws as the loop)
    assert all("strata" not in kw and kw["move_beta"] == 2.0 for kw in calls)
    calls.clear()
    try:
        belief.stratify = True
        es.build_worlds(None, belief, (), random.Random(1), 4)
        assert [kw["strata"][:2] for kw in calls] == [(j, 4) for j in range(4)]
        assert len({kw["strata"][2] for kw in calls}) == 1  # (one seed per decision)
    finally:
        belief.stratify = False
