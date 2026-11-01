"""Bot factory for local evaluations (all bots connect to local servers only)."""

import os

from poke_env.player import MaxBasePowerPlayer, Player, RandomPlayer, SimpleHeuristicsPlayer

# bot name -> (player class: "knowledge" heuristic / "search" ISMCTS / "policy" network policy,
# keyword arguments). Older variants (LLM plans, determinized search, the MLP network, the
# heuristic bot's ablations) were removed on 2026-10-08; their results stay in doc/results.md.
# the default network of the variants that take ALPHA_MODEL_A / _B (2026-10-28: the self-play
# start, runner.MODEL; was v5-glu)
from alpha_poke.selfplay.runner import MODEL as DEFAULT_MODEL  # noqa: E402
from alpha_poke.servers import account, local_server

VARIANTS: dict[str, tuple[str, dict]] = {
    # heuristic bot with the computed plan (play_public's easy level)
    "knowledge": ("knowledge", {}),
    # ISMCTS (design D12), one tree over 32 belief worlds, handcrafted evaluation at the leaves
    "s_ismcts": ("search", {"worlds": 32}),
    # CPU ISMCTS with the model given at run time (ALPHA_MODEL_A / ALPHA_MODEL_B): comparisons
    # of any two networks, Foul Play anchors, games against humans (scripts/play_public.py)
    **{
        f"s_ismcts_m{x}": (
            "search",
            {
                "worlds": 32,
                "net_policy": "both",
                "model": os.environ.get(f"ALPHA_MODEL_{x.upper()}", DEFAULT_MODEL),
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
                "model": os.environ.get(f"ALPHA_MODEL_{x.upper()}", DEFAULT_MODEL),
                "dtype": os.environ.get(f"ALPHA_GPU_DTYPE_{x.upper()}"),
                # per side (equal-cost comparisons of networks of different sizes); else
                # ALPHA_SEARCH_ITERATIONS
                "iters": os.environ.get(f"ALPHA_SEARCH_ITERATIONS_{x.upper()}"),
                # the moves-left term "slope,cap,threshold" (selfplay.batcher.parse_ml; v6)
                "ml": os.environ.get(f"ALPHA_ML_{x.upper()}"),
                # (2026-10-31) regret matching at the root (its exploration weight; 0 = PUCT)
                # and the mixed choice where it is a guess (the value margin; 0 = the most visited)
                "root_rm": os.environ.get(f"ALPHA_ROOT_RM_{x.upper()}"),
                "mix": os.environ.get(f"ALPHA_MIX_{x.upper()}"),
                # (2026-10-31) the belief's switches, comma-separated (BeliefModel's booleans):
                # rake, f1_all, stratify
                "belief": os.environ.get(f"ALPHA_BELIEF_{x.upper()}"),
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
            {
                "model": os.environ.get(f"ALPHA_MODEL_{x.upper()}", DEFAULT_MODEL),
                "tau": 0.05,
                "rating": 0,
            },
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
    overrides: dict | None = None,
) -> Player:
    """``team``: a Showdown-format team (replaced per battle with ``update_team``).
    ``heldout_pool``: use the belief model trained without that pool's teams. ``overrides``:
    keyword arguments replacing the variant's own (e.g. its ``model``)."""
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
        extra = extra | (overrides or {})
        if cls_name == "batched":
            return _batched_bot(extra["model"], heldout_pool, trace_dir, kw, extra.get("dtype"),
                                extra.get("iters"), extra.get("ml"), extra.get("root_rm"),
                                extra.get("mix"), extra.get("belief"))  # fmt: skip
        if cls_name == "search":
            from alpha_poke.agents.search_player import SearchPlayer as cls
        elif cls_name == "policy":
            from alpha_poke.agents.policy_player import PolicyPlayer as cls
        else:
            from alpha_poke.agents.knowledge_player import KnowledgePlayer as cls
        belief = BeliefModel.load(heldout_pool=heldout_pool)
        return cls(belief, trace_dir=trace_dir, **extra, **kw)
    return BASELINES[kind](**kw)


# (model, dtype, ml) -> Batcher, one per network in each (worker) process
_BATCHERS: dict = {}


def _batched_bot(model: str, heldout_pool, trace_dir, kw, dtype: str | None = None,
                 iters: str | None = None, ml: str | None = None, root_rm: str | None = None,
                 mix: str | None = None, belief_opts: str | None = None) -> Player:  # fmt: skip
    import random

    from alpha_poke.agents.belief_state import BeliefModel
    from alpha_poke.selfplay.batcher import Batcher, parse_ml
    from alpha_poke.selfplay.player import SelfPlayPlayer

    key = (model, dtype, parse_ml(ml), float(root_rm or 0))
    if key not in _BATCHERS:
        _BATCHERS[key] = Batcher(model, leaves=8, threads=2, dtype=dtype, ml=key[2], root_rm=key[3])
    iters = int(iters or os.environ.get("ALPHA_SEARCH_ITERATIONS") or 3000)
    belief = BeliefModel.load(heldout_pool=heldout_pool)
    for opt in filter(None, (belief_opts or "").split(",")):
        if not isinstance(getattr(BeliefModel, opt, None), bool):
            raise ValueError(f"ALPHA_BELIEF: no belief switch {opt!r}")
        setattr(belief, opt, True)
    return SelfPlayPlayer(
        belief, trace_dir=trace_dir, worlds=32,
        net_policy="both", model=model, batcher=_BATCHERS[key], full_frac=1.0,
        full_iters=iters, noise=(0.0, 10.0), greedy=True, record=False, mix=float(mix or 0),
        turn_cap=int(os.environ.get("ALPHA_TURN_CAP", 300)),
        seed=random.randrange(1 << 30), **kw,
    )  # fmt: skip
