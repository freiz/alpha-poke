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
