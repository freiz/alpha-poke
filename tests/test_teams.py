from alpha_poke.teams import TeamPool, load_team_files


def test_team_pool_yields_packed_six_mon_teams():
    teams = load_team_files()
    assert teams
    pool = TeamPool(seed=0)
    for _ in range(5):
        assert len(pool.parse_packed_team(pool.yield_team())) == 6


SET = """{name} @ Leftovers
Ability: Pressure
Tera Type: Fairy
EVs: 252 HP / 4 Def / 252 SpD
Calm Nature
- Protect
- Toxic
- Recover
- Ice Beam"""


def test_inline_teams():
    from alpha_poke.teams.forum import inline_teams

    sets = [SET.format(name=f"Nick (Mon{i})" if i == 2 else f"Mon{i}") for i in range(6)]
    # the RMT layout: sets with commentary in between, blank lines inside sets
    rmt = "\n\nWhy this set: reasons.\n\n".join(s.replace("\n", "\n\n") for s in sets)
    (team,) = inline_teams(f"My team!\n\n{rmt}\n\nThanks.\n\n{sets[0]}")  # Mon0 repeated
    assert team.count("Ability:") == 6 and "Why" not in team
    # the importable at the end wins over the annotated sets
    alt = [s.replace("Ice Beam", "Scald") for s in sets]
    (team,) = inline_teams(rmt + "\n\nImportable:\n" + "\n\n".join(alt))
    assert team.count("Scald") == 6
    # a set dump (8 species) or a partial team is not a team
    assert inline_teams("\n\n".join(SET.format(name=f"M{i}") for i in range(8))) == []
    assert inline_teams("\n\n".join(sets[:5])) == []


def test_posts_and_paste_links():
    from alpha_poke.teams.forum import PASTE_RE, posts

    page = (
        '<article class="message message--post" data-author="A" data-content="post-11">'
        '<time class="u-dt" datetime="2024-01-02T03:04:05-0500"></time>'
        '<div class="bbWrapper">see https://pokepast.es/0123456789abcdef</div>'
        '<aside class="message-signature">https://pokepast.es/ffffffffffffffff</aside></article>'
    )
    (p,) = posts(page)
    assert (p["post"], p["author"], p["date"][:10]) == (11, "A", "2024-01-02")
    assert PASTE_RE.findall(p["body"]) == ["0123456789abcdef"]  # signature dropped


def test_preview_key_and_completeness():
    from alpha_poke.teams.catalog import is_complete
    from alpha_poke.teams.validate import preview_name, team_key

    assert preview_name("Zamazenta") == "Zamazenta-*"
    assert preview_name("Zamazenta-Crowned") == "Zamazenta-Crowned"
    assert preview_name("Urshifu-Rapid-Strike") == "Urshifu-*"
    assert team_key(["Kingambit", "Gholdengo"]) == "Gholdengo|Kingambit"
    six = "\n\n".join(SET.format(name=f"M{i}") for i in range(6))
    assert is_complete(six) and not is_complete(six.replace("- Ice Beam", ""))


def test_catalog_near_duplicates_share_a_family():
    """teams.catalog.families: the same six species with at most NEAR_DIFF differences (an item,
    an ability, a tera type, a swapped move; spreads ignored) join one family, its
    representative the entry with the most sources; a team three changes away stays apart."""
    from alpha_poke.teams.catalog import Entry, families

    def team(item="Leftovers", move="Roost", tera="Water"):
        sets = [
            f"Mon{i} @ {item if i == 0 else 'Leftovers'}\nAbility: A\nTera Type: {tera if i == 0 else 'Fire'}\n"
            f"EVs: 252 HP\n- {move if i == 0 else 'Tackle'}\n- B\n- C\n- D"
            for i in range(6)
        ]
        return "\n\n".join(sets)

    base = Entry("a", "k", team(), True, "2026-01-01", [{"source": "rmt"}, {"source": "sample"}])
    tweak = Entry(
        "b",
        "k",
        team(move="Recover").replace("252 HP", "248 HP"),
        True,
        "2025-01-01",
        [{"source": "rmt"}],
    )
    far = Entry(
        "c",
        "k",
        team(item="Life Orb", move="Earthquake", tera="Fire"),
        True,
        "2026-02-01",
        [{"source": "rmt"}],
    )
    families([base, tweak, far])
    assert base.family == tweak.family == "a" and far.family == "c"


def test_catalog_reads_a_paste_once_and_keeps_every_source(monkeypatch):
    """teams.catalog.build: a paste linked by several posts and sources is validated once; its
    entry keeps every source and the earliest date."""
    from alpha_poke.teams import catalog

    calls = []

    def check(texts, fmt="gen9ou"):
        calls.append(len(texts))
        return [
            {"n": 6, "species": [f"S{i}" for i in range(6)], "text": t, "problems": []}
            for t in texts
        ]

    monkeypatch.setattr(catalog, "check", check)
    monkeypatch.setattr(
        catalog.pokepaste,
        "load",
        lambda pid: {"title": "T", "notes": "Format: gen9ou", "paste": "x"},
    )
    links = [{"source": "rmt", "date": "2026-03-01", "paste": "p1"},
             {"source": "wayback", "date": "2026-01-01", "paste": "p1"}]  # fmt: skip
    es = catalog.build(links, log=lambda *a: None)
    assert calls == [1] and len(es) == 1
    assert {s["source"] for s in es[0].sources} == {"rmt", "wayback"} and es[0].date == "2026-01-01"
