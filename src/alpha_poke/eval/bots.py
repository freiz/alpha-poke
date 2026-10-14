"""Bot factory for local evaluations (all bots connect to local servers only)."""

import os

from poke_env.player import MaxBasePowerPlayer, Player, RandomPlayer, SimpleHeuristicsPlayer

from alpha_poke.servers import account, local_server

# bot name -> (player class: "knowledge" heuristic / "search" ISMCTS / "policy" network policy,
# keyword arguments). Older variants (LLM plans, determinized search, the MLP network, the
# heuristic bot's ablations) were removed on 2026-10-08; their results stay in doc/results.md.
GLU = "data/train/v5/runs/v5-glu"
VARIANTS: dict[str, tuple[str, dict]] = {
    # heuristic bot with the computed plan (play_public's easy level)
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
    # the same search, the networks on the GPU: every game of a process shares one batcher per
    # network (selfplay.batcher, as in self-play) — no root noise, the most visited option,
    # ALPHA_SEARCH_ITERATIONS (default 3,000) iterations and 32 worlds per decision
    **{
        f"g_m{x}": (
            "batched",
            {
                "model": os.environ.get(f"ALPHA_MODEL_{x.upper()}", GLU),
                "dtype": os.environ.get(f"ALPHA_GPU_DTYPE_{x.upper()}"),
                # per side (equal-cost comparisons of networks of different sizes); else
                # ALPHA_SEARCH_ITERATIONS
                "iters": os.environ.get(f"ALPHA_SEARCH_ITERATIONS_{x.upper()}"),
                # ALPHA_STATE_FIXES_A / _B: the engine-state fix level (engine_state.fix_level:
                # 0 as before 2026-10-11, 1 the first batch, 2 the second, 3 all; A/B tests)
                "fixes": int(os.environ.get(f"ALPHA_STATE_FIXES_{x.upper()}", "3")),
                # ALPHA_TIEBREAK_A / _B: the root tie-break (agents.tiebreak; 2026-10-14): "1"
                # (defaults) or "delta,q_min,min_share"; unset / "0": off
                "tiebreak": os.environ.get(f"ALPHA_TIEBREAK_{x.upper()}", ""),
                # ALPHA_LEGACY_CONTEXT_A / _B = 1: the search's tree-path context as before
                # 2026-10-14 (A/B tests)
                "legacy": os.environ.get(f"ALPHA_LEGACY_CONTEXT_{x.upper()}") == "1",
            },
        )
        for x in ("a", "b")
    },  # fmt: skip
    # no search: the network's own policy (argmax-like, tau 0.05; rating input unknown, as the
    # bots in self-play), the model given at run time — comparisons of two networks without
    # the search making up for the prior
    **{
        f"p_m{x}": (
            "policy",
            {"model": os.environ.get(f"ALPHA_MODEL_{x.upper()}", GLU), "tau": 0.05, "rating": 0},
        )
        for x in ("a", "b")
    },  # fmt: skip
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
        if cls_name == "batched":
            return _batched_bot(extra["model"], heldout_pool, trace_dir, kw, extra.get("dtype"),
                                extra.get("iters"), extra.get("fixes", 2),
                                extra.get("tiebreak", ""), extra.get("legacy", False))  # fmt: skip
        if cls_name == "search":
            from alpha_poke.agents.search_player import SearchPlayer as cls
        elif cls_name == "policy":
            from alpha_poke.agents.policy_player import PolicyPlayer as cls
        else:
            from alpha_poke.agents.knowledge_player import KnowledgePlayer as cls
        belief = BeliefModel.load(heldout_pool=heldout_pool)
        return cls(belief, trace_dir=trace_dir, **extra, **kw)
    return BASELINES[kind](**kw)


_BATCHERS: dict = {}  # (model, dtype) -> Batcher, one per network in each (worker) process


def _batched_bot(model: str, heldout_pool, trace_dir, kw, dtype: str | None = None,
                 iters: str | None = None, fixes: int = 2, tiebreak: str = "",
                 legacy: bool = False) -> Player:  # fmt: skip
    import random

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay.batcher import Batcher
    from alpha_poke.selfplay.player import SelfPlayPlayer

    if (model, dtype) not in _BATCHERS:
        _BATCHERS[model, dtype] = Batcher(model, leaves=8, threads=2, dtype=dtype)
    iters = int(iters or os.environ.get("ALPHA_SEARCH_ITERATIONS") or 3000)
    tb = None
    if tiebreak not in ("", "0"):
        from alpha_poke.agents.tiebreak import TieBreak

        tb = TieBreak(*map(float, tiebreak.split(","))) if "," in tiebreak else TieBreak()
    return SelfPlayPlayer(
        BeliefModel.load(heldout_pool=heldout_pool), trace_dir=trace_dir, worlds=32,
        net_policy="both", model=model, batcher=_BATCHERS[model, dtype], full_frac=1.0,
        full_iters=iters, noise=(0.0, 10.0), greedy=True, record=False,
        turn_cap=int(os.environ.get("ALPHA_TURN_CAP", 300)),
        seed=random.randrange(1 << 30), state_fixes=fixes, tiebreak=tb, legacy_context=legacy,
        **kw,
    )  # fmt: skip
