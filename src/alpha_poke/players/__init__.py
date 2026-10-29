"""Models of one specific opponent (design D5-O): their games, team distribution, sets and
play. Public data only (their uploaded replays, our games against them). Per-player data lives
in ``data/players/<user id>/`` (git-ignored: user names stay out of the repository).

Modules: ``games`` (collect and parse their games), ``team_model`` (step 1: team and set
distribution), ``play_model`` (step 2: the network's rating input and temperature that best
explain their decisions). CLI: ``scripts/player.py``.
"""


from alpha_poke import paths

PLAYERS_DIR = paths.PLAYERS
