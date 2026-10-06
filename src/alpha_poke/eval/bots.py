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
    "k_llmplan": (True, True, True, {"plan_mode": "llm"}),
    # search (belief-sampled poke-engine MCTS); budget via ALPHA_SEARCH_MS / _SAMPLES / _THREADS
    "s_llmplan": (True, True, True, {"plan_mode": "llm", "search": True}),
    "s_computed": (True, True, True, {"search": True}),
    # + root plan prior (design D11, A1): visit share + plan_prior * plan bonus
    "s_llmplan_prior": (True, True, True, {"plan_mode": "llm", "search": True, "plan_prior": 0.3}),
    "s_computed_prior": (True, True, True, {"search": True, "plan_prior": 0.3}),
    # oracle upper bound (D11 B): the opponent's TRUE sets instead of belief samples (local
    # evaluation only: the evaluator passes the opponent's team with set_oracle)
    "s_oracle": (True, True, True, {"plan_mode": "llm", "search": True, "oracle": True}),
    # samples per decision at a fixed total budget (B1; computed plan, no LLM)
    **{f"s_c_k{k}": (True, True, True, {"search": True, "samples": k}) for k in (1, 2, 8, 16)},
    # sampled moves weighted by the team-conditioned move prior ** beta (computed plan, no LLM);
    # the search default is beta 1 (= s_c_tm1); s_c_tm0 = the archetype-only sampler before it
    **{
        f"s_c_tm{b}": (True, True, True, {"search": True, "move_beta": float(b)})
        for b in (0, 1, 2, 3)
    },
    # ISMCTS backend (design D12; computed plan, no LLM): one tree over N belief worlds
    "s_ismcts": (True, True, True, {"search": True, "backend": "ismcts", "worlds": 32}),
    "s_ismcts_n1": (True, True, True, {"search": True, "backend": "ismcts", "worlds": 1}),
    "s_ismcts_cl2": (
        True,
        True,
        True,
        {"search": True, "backend": "ismcts", "worlds": 32, "chance_depth": 2},
    ),  # fmt: skip
    # oracle decomposition (computed plan, no LLM): only one kind of true information each
    "s_c_oracle": (True, True, True, {"search": True, "oracle": True}),
    **{
        f"s_c_oracle_{f}": (True, True, True, {"search": True, "oracle": f})
        for f in ("item", "moves", "tera", "spread")
    },
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
        from alpha_poke.agents.knowledge_player import KnowledgePlayer
        from alpha_poke.library import load_library

        full, use_plan, plan_lead, extra = VARIANTS[kind]
        belief = BeliefModel.load(heldout_pool=heldout_pool)
        if not full:
            belief = belief.marginal_only()
        extra = dict(extra)
        cls = KnowledgePlayer
        if extra.pop("search", False):
            from alpha_poke.agents.search_player import SearchPlayer

            cls = SearchPlayer
        return cls(
            belief,
            library=load_library(),
            use_plan=use_plan,
            plan_lead=plan_lead,
            trace_dir=trace_dir,
            **extra,
            **kw,
        )
    return BASELINES[kind](**kw)
