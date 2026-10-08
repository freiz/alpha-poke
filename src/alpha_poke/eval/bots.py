"""Bot factory for local evaluations (all bots connect to local servers only)."""

import os

from poke_env.player import MaxBasePowerPlayer, Player, RandomPlayer, SimpleHeuristicsPlayer

from alpha_poke.servers import account, local_server

# bot name -> (player class: "knowledge" heuristic / "search" ISMCTS / "policy" network policy,
# keyword arguments). Older variants (LLM plans, determinized search, the MLP network, the
# heuristic bot's ablations) were removed on 2026-10-08; their results stay in doc/results.md.
GLU = "data/train/v5/runs/v5-glu"
VARIANTS: dict[str, tuple[str, dict]] = {
    # heuristic bot with the computed plan (design D9; play_public's easy level)
    "knowledge": ("knowledge", {}),
    # ISMCTS (design D12), one tree over 32 belief worlds, handcrafted evaluation at the leaves
    "s_ismcts": ("search", {"worlds": 32}),
    # + the v5-glu network (design D13): priors for both sides and leaf values; CPU / GPU
    **{
        f"s_ismcts_glu{suffix}": (
            "search",
            {"worlds": 32, "net_policy": "both", "model": GLU, **extra},
        )  # fmt: skip
        for suffix, extra in (("", {}), ("g", {"device": "cuda"}))
    },
    # CPU ISMCTS with the model given at run time (ALPHA_MODEL_A / ALPHA_MODEL_B): comparisons
    # of any two networks, e.g. self-play generations (scripts/selfplay.py eval)
    **{
        f"s_ismcts_m{x}": (
            "search",
            {
                "worlds": 32,
                "net_policy": "both",
                "model": os.environ.get(f"ALPHA_MODEL_{x.upper()}", GLU),
            },
        )  # fmt: skip
        for x in ("a", "b")
    },
    # no search: the network's policy sampled with a temperature and a rating input, the model
    # of a specific human (design D5-O step 2); rating / tau via ALPHA_POLICY_RATING /
    # ALPHA_POLICY_TAU (scripts/counter_team.py sets them from the player's fit to v5-final)
    "pol": ("policy", {"model": "data/train/v5/runs/v5-final"}),
}
BASELINES = {
    "heuristic": SimpleHeuristicsPlayer,
    "max_bp": MaxBasePowerPlayer,
    "random": RandomPlayer,
}
BOT_NAMES = sorted(VARIANTS) + sorted(BASELINES)


def make_bot(
    kind: str,
    name: str,
    port: int,
    team: str,
    concurrency: int = 1,
    heldout_pool: str | None = None,
    trace_dir: str | None = None,
    replay_dir: str | None = None,
    server_configuration=None,
    account_configuration=None,
) -> Player:
    """``team``: a Showdown-format team (replaced per battle with ``update_team``).
    ``heldout_pool``: use the belief model trained without that pool's teams."""
    kw = dict(
        account_configuration=account_configuration or account(name),
        battle_format="gen9ou",
        server_configuration=server_configuration or local_server(port),
        max_concurrent_battles=concurrency,
        team=team,
    )
    if replay_dir:
        kw["save_replays"] = replay_dir
    if kind in VARIANTS:
        from alpha_poke.agents.belief_state import BeliefModel

        cls_name, extra = VARIANTS[kind]
        if cls_name == "search":
            from alpha_poke.agents.search_player import SearchPlayer as cls
        elif cls_name == "policy":
            from alpha_poke.agents.policy_player import PolicyPlayer as cls
        else:
            from alpha_poke.agents.knowledge_player import KnowledgePlayer as cls
        belief = BeliefModel.load(heldout_pool=heldout_pool)
        return cls(belief, trace_dir=trace_dir, **extra, **kw)
    return BASELINES[kind](**kw)
