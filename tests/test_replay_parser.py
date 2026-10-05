import json
from pathlib import Path

import pytest

from alpha_poke.replay import parse_replay

FIXTURE = Path(__file__).parent / "fixtures" / "gen9ou_sample.json"


@pytest.fixture(scope="module")
def sample():
    return parse_replay(json.loads(FIXTURE.read_text()))


def mon(replay, side, species):
    return next(m for m in replay.teams[side] if m.species == species)


def test_header_and_result(sample):
    assert sample.format == "gen9ou" and sample.gen == 9
    assert sample.turns == 15
    assert sample.players == {"p1": "PlayerOne", "p2": "PlayerTwo"}
    assert sample.winner == "p1"
    assert sample.ratings_before == {"p1": 1686, "p2": 1664}
    assert sample.ratings_after == {"p1": 1705, "p2": 1645}


def test_teams_and_leads(sample):
    assert [len(sample.teams[s]) for s in ("p1", "p2")] == [6, 6]
    assert sample.leads() == {"p1": "Glimmora", "p2": "Glimmora"}
    assert not mon(sample, "p1", "Garchomp").brought
    assert mon(sample, "p1", "Glimmora").lead


def test_reveals(sample):
    cer = mon(sample, "p2", "Ceruledge")
    assert cer.item == "Air Balloon" and cer.ability == "Weak Armor"
    assert cer.tera_type == "Fairy" and cer.tera_turn == 10
    assert cer.moves == ["Shadow Sneak", "Swords Dance", "Close Combat"]
    assert mon(sample, "p2", "Glimmora").item == "Focus Sash"  # via -enditem
    assert mon(sample, "p2", "Kingambit").item == "Leftovers"  # via [from] item: on -heal
    assert mon(sample, "p1", "Glimmora").ability == "Toxic Debris"  # via -activate


def test_actions_and_field(sample):
    tera = [a for a in sample.actions if a.tera]
    assert len(tera) == 1 and tera[0].mon == "Ceruledge" and tera[0].move == "Swords Dance"
    forced = [a for a in sample.actions if a.kind == "switch" and a.forced]
    assert len(forced) == 9  # 10 faints; the one that ends the game has no replacement
    hazards = [(e["side"], e["detail"]) for e in sample.field_events if e["kind"] == "sidestart"]
    assert ("p1", "Stealth Rock") in hazards and ("p1", "Spikes") in hazards
    assert sample.hp_by_turn[2]["p2"] == ("Glimmora", 1)
    assert not sample.warnings


def test_team_sheet_text(sample):
    text = sample.team_sheet("p2")
    assert "Ceruledge @ Air Balloon" in text and "Tera Type: Fairy" in text


# ---- synthetic edge cases -------------------------------------------------------------


def synth(*body: str) -> dict:
    head = [
        "|player|p1|A|x|1500",
        "|player|p2|B|x|1500",
        "|gametype|singles",
        "|gen|9",
        "|poke|p1|Garchomp, M|",
        "|poke|p1|Zoroark-Hisui, M|",
        "|poke|p2|Great Tusk|",
        "|poke|p2|Urshifu-*|",
        "|start",
    ]
    return {"id": "synth", "formatid": "gen9ou", "log": "\n".join(head + list(body))}


def test_pivot_and_called_moves():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            "|move|p1a: G|Metronome|p1a: G",
            "|move|p1a: G|Earthquake|p2a: T|[from]move: Metronome",
            "|move|p2a: T|Rapid Spin|p1a: G",
            "|switch|p2a: U|Urshifu-Rapid-Strike, M|100/100",
            "|turn|2",
        )
    )
    assert mon(r, "p1", "Garchomp").moves == ["Metronome"]
    sw = [a for a in r.actions if a.kind == "switch"][0]
    assert sw.pivot and not sw.forced and sw.to == "Urshifu-*"
    assert mon(r, "p2", "Urshifu-*").forms == ["Urshifu-Rapid-Strike"]


def test_item_holder_uses_of_tag():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            "|move|p1a: G|Earthquake|p2a: T",
            "|-damage|p1a: G|88/100|[from] item: Rocky Helmet|[of] p2a: T",
        )
    )
    assert mon(r, "p2", "Great Tusk").item == "Rocky Helmet"
    assert mon(r, "p1", "Garchomp").item is None


def test_illusion_phantom_merged_on_replace():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            "|switch|p1a: Z|Gengar, M|100/100",
            "|move|p1a: Z|Shadow Ball|p2a: T",
            "|replace|p1a: Zoroark|Zoroark-Hisui, M",
        )
    )
    assert [m.species for m in r.teams["p1"]] == ["Garchomp", "Zoroark-Hisui"]
    assert mon(r, "p1", "Zoroark-Hisui").moves == ["Shadow Ball"]
    assert any("Illusion" in w for w in r.warnings)


@pytest.mark.skipif(not Path("data/replays_sample").exists(), reason="no local sample replays")
def test_all_local_samples_parse():
    for f in Path("data/replays_sample").glob("*.json"):
        r = parse_replay(json.loads(f.read_text()))
        assert r.winner in ("p1", "p2") and len(r.teams["p1"]) >= 6


def test_generic_from_tags_reveal_ability_and_item():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            "|-immune|p1a: G|[from] ability: Good as Gold",
            "|-status|p2a: T|brn|[from] item: Flame Orb",
            "|-item|p2a: T|Leftovers|[from] ability: Frisk|[of] p1a: G",
        )
    )
    assert mon(r, "p1", "Garchomp").ability == "Good as Gold"
    assert mon(r, "p2", "Great Tusk").item == "Flame Orb"


def test_ability_holder_semantics():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            # Water Absorb heals the line mon; [of] is the attacker
            "|-heal|p1a: G|100/100|[from] ability: Water Absorb|[of] p2a: T",
            # Pickpocket: the line mon stole the [of] mon's item
            "|-item|p2a: T|Heavy-Duty Boots|[from] ability: Pickpocket|[of] p1a: G",
            "|turn|2",
            "|-activate|p1a: G|move: Skill Swap|Rough Skin|Protosynthesis|[of] p2a: T",
            "|-ability|p1a: G|Protosynthesis",
        )
    )
    g, t = mon(r, "p1", "Garchomp"), mon(r, "p2", "Great Tusk")
    assert g.ability == "Water Absorb"  # first reveal; the swapped one is ignored
    assert t.ability == "Pickpocket"
    assert t.item is None  # the stolen Boots were not Great Tusk's original item


def test_rough_skin_damage_belongs_to_of_mon():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            "|-damage|p2a: T|90/100|[from] ability: Rough Skin|[of] p1a: G",
        )
    )
    assert mon(r, "p1", "Garchomp").ability == "Rough Skin"
    assert mon(r, "p2", "Great Tusk").ability is None


def test_contact_ability_status_belongs_to_of_mon():
    r = parse_replay(
        synth(
            "|switch|p1a: G|Garchomp, M|100/100",
            "|switch|p2a: T|Great Tusk|100/100",
            "|turn|1",
            "|-status|p2a: T|brn|[from] ability: Flame Body|[of] p1a: G",
            "|-immune|p2a: T|[from] ability: Volt Absorb|[of] p1a: G",
        )
    )
    assert mon(r, "p1", "Garchomp").ability == "Flame Body"
    assert mon(r, "p2", "Great Tusk").ability == "Volt Absorb"
