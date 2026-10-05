"""Bot factory for local evaluations (all bots connect to local servers only)."""

from poke_env.player import MaxBasePowerPlayer, Player, RandomPlayer, SimpleHeuristicsPlayer

from alpha_poke.servers import account, local_server

# knowledge-bot variants: name -> (full belief, use plan, plan lead, extra kwargs)
VARIANTS: dict[str, tuple[bool, bool, bool, dict]] = {
    "knowledge": (True, True, True, {}),
    "knowledge_twin": (True, True, True, {}),  # identical to "knowledge" (sanity check)
    "k_nobelief": (False, True, True, {}),
    "k_noplan": (True, False, False, {}),
    "k_nolead": (True, True, False, {}),
    "k_randlead": (True, True, True, {"random_lead": True}),
    "k_uniformlead": (True, True, True, {"lead_prior": "uniform"}),
    "k_none": (False, False, False, {}),
    "k_noloopfix": (True, True, True, {"anti_loop": False}),
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
) -> Player:
    """``team``: a Showdown-format team (replaced per battle with ``update_team``).
    ``heldout_pool``: use the belief model trained without that pool's teams."""
    kw = dict(
        account_configuration=account(name),
        battle_format="gen9ou",
        server_configuration=local_server(port),
        max_concurrent_battles=concurrency,
        team=team,
    )
    if replay_dir:
        kw["save_replays"] = replay_dir
    if kind in VARIANTS:
        from alpha_poke.agents.belief_state import BeliefModel
        from alpha_poke.agents.knowledge_player import KnowledgePlayer
        from alpha_poke.library import load_library

        full, use_plan, plan_lead, extra = VARIANTS[kind]
        belief = BeliefModel.load(heldout_pool=heldout_pool)
        if not full:
            belief = belief.marginal_only()
        return KnowledgePlayer(
            belief,
            library=load_library(),
            use_plan=use_plan,
            plan_lead=plan_lead,
            trace_dir=trace_dir,
            **extra,
            **kw,
        )
    return BASELINES[kind](**kw)
