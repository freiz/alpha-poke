"""The self-play player (design D15-2/3): ISMCTS with the network on the GPU, search settings of
D5 (playout cap randomization, root noise, the move sampled from the visits), and a record of
every decision: the root's network input (world 0 and its context) and the search result in
the network's action slots (``BatchSearch.record``).

Records stay on the player per battle (``records[battle_tag]``); the runner collects them after
each game and adds what only the whole game knows (outcome, the true teams)."""

import asyncio
import logging
import random
import time

from poke_env.player.battle_order import ForfeitBattleOrder

from alpha_poke.agents import net_context
from alpha_poke.agents.consistency import request_mismatch
from alpha_poke.agents.engine_state import build_state, engine_move_to_order
from alpha_poke.agents.knowledge_player import KnowledgePlayer, sync_tera_types
from alpha_poke.agents.search_player import SearchPlayer
from alpha_poke.train.positions import KIND_FORCED, KIND_MAIN, KIND_PIVOT

log = logging.getLogger(__name__)


def foe_move_weights(state, rec: dict) -> dict[str, float]:
    """The opponent's root visits by move id (``BatchSearch.record``'s ``opp_visits``: its action
    slots in world 0 -- moves 0-3, the same with tera 4-7; switches left out)."""
    side = state.side_two
    moves = [m.id for m in side.pokemon[int(side.active_index)].moves]
    out: dict[str, float] = {}
    for i, v in enumerate(rec.get("opp_visits") or []):
        if i < 8 and v > 0 and i % 4 < len(moves) and moves[i % 4] != "none":
            out[moves[i % 4]] = out.get(moves[i % 4], 0.0) + float(v)
    return out


def order_is(order, name: str) -> bool:
    """Is the poke-env ``order`` the searched option ``name`` ('earthquake', 'earthquake-tera',
    'switch greattusk')?"""
    o = order.order
    if name.startswith("switch "):
        return getattr(o, "species", None) == name.split(" ", 1)[1]
    tera = name.endswith("-tera")
    return getattr(o, "id", None) == name.removesuffix("-tera") and bool(order.terastallize) == tera


class SelfPlayPlayer(SearchPlayer):
    """``batcher``: the process's ``selfplay.batcher.Batcher`` (shared by all its games);
    ``choose_move`` is asynchronous (poke-env awaits it), so other games go on while this one
    waits for its search."""

    def __init__(self, *args, batcher=None, full_frac: float = 0.25, full_iters: int = 3000,
                 fast_iters: int = 600, fast_worlds: int = 16,
                 noise: tuple[float, float] = (0.1, 10.0), turn_cap: int = 300, seed: int = 0,
                 greedy: bool = False, record: bool = True, temp_turns: int = 8,
                 temp_late: float = 0.25, loop: tuple | None = None, **kwargs):  # fmt: skip
        super().__init__(*args, **kwargs)
        assert self.model_transformer and batcher is not None
        self.batcher = batcher
        self.full_frac, self.full_iters, self.fast_iters = full_frac, full_iters, fast_iters
        self.fast_worlds, self.noise, self.turn_cap = fast_worlds, noise, turn_cap
        self.search_timeout = 120.0
        self.rng = random.Random(seed)
        self.records: dict[str, list[dict]] = {}
        # evaluation (eval.bots g_ma / g_mb): the most visited option, nothing recorded
        self.greedy, self.record = greedy, record
        # the move: sampled from the visits ** (1 / tau), tau = 1 for the first ``temp_turns``
        # turns (variety), then ``temp_late`` (AlphaZero / KataGo: later blunders would make
        # the outcome a noisy label of the position: in gen 2 only 58% of the moves played were
        # the most visited)
        self.temp_turns, self.temp_late = temp_turns, temp_late
        # stalling loops (2026-10-14, design "防拖延循环"): (quiet, switches, window, tau, eps):
        # when no mon has fainted for ``quiet`` turns and this side switched in ``switches`` of
        # its last ``window`` turns, its moves are sampled at ``tau`` with root noise ``eps``
        # (the loop broken and played out, its states get outcomes); None: off
        self.loop = loop
        # the request each battle's last record answered (a refused choice drops its record)
        self._record_request: dict[str, int] = {}
        self.dropped_records = 0
        # the opponent's root visits by move id at each battle's last turn-start search, (turn,
        # weights): its move still to come after our pivot that turn is drawn from them
        # (engine_state.build_state foe_pending; 2026-10-22 review)
        self._foe_moves: dict[str, tuple[int, dict]] = {}

    def choose_move(self, battle):
        return self._choose_selfplay(battle)

    def looping(self, battle) -> bool:
        """This side in a stalling loop (``loop``), from the battle's log (kept on the battle,
        fed the new messages)."""
        if not self.loop:
            return False
        quiet, switches, window = self.loop[:3]
        data = battle._replay_data
        n, st = getattr(battle, "_alpha_loop", (0, None))
        if st is None or n > len(data):
            n, st = 0, {"turn": 0, "faint": 0, "switched": False, "turns": []}
        me = battle.player_role or "p1"
        for m in data[n:]:
            if len(m) < 3:
                continue
            if m[1] == "turn":
                if st["turn"] > 0:
                    st["turns"] = (st["turns"] + [st["switched"]])[-window:]
                st["turn"], st["switched"] = int(m[2]), False
            elif m[1] == "switch" and m[2].startswith(me) and st["turn"] > 0:
                st["switched"] = True
            elif m[1] == "faint":
                st["faint"] = st["turn"]
        battle._alpha_loop = (len(data), st)
        return st["turn"] - st["faint"] >= quiet and sum(st["turns"]) >= switches

    async def _choose_selfplay(self, battle):
        if battle.turn >= self.turn_cap:
            # stalling loops (e.g. endless switching): end the game; the runner marks it capped
            # (its decisions valued as a draw: selfplay.convert)
            return ForfeitBattleOrder()
        try:
            order = await self._search_async(battle)
            if order is not None:
                return order
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except BaseException:  # noqa: BLE001 - never lose a game to a search bug
            log.exception("self-play search failed; heuristic decision")
        self.search_fallbacks += 1
        return KnowledgePlayer.choose_move(self, battle)

    async def _revive_async(self, battle):
        """Revival Blessing's choice (SearchPlayer._revive): each candidate's state after it,
        a fast search each (in parallel on the batcher), the best root value; not recorded (no
        such action in the network's slots)."""
        cands = list(battle.available_switches)
        if len(cands) <= 1:
            return self.create_order(cands[0]) if cands else None
        names = self._opp_team_names(battle)
        futs = []
        for m in cands:
            states = [build_state(battle, self.belief, names, self.rng, move_beta=self.move_beta,
                                  damage_belief=self.damage_belief, arch_mix=self.arch_mix,
                                  force_switch=False, revived=m.species)
                      for _ in range(self.fast_worlds)]  # fmt: skip
            ctxs = net_context.contexts(battle, states, self.batcher.post)
            futs.append((m, self.batcher.submit([s.to_string() for s in states], ctxs,
                                                self.fast_iters, self.rng.randrange(1 << 30),
                                                (0.0, 10.0))))  # fmt: skip
        vals = {}
        for m, fut in futs:
            res = await asyncio.wait_for(asyncio.wrap_future(fut), timeout=self.search_timeout)
            vals[m.species] = res[0]["q"]
        self.revives += 1
        best = max(cands, key=lambda m: vals[m.species])
        log.info("revive (%s turn %d): %s", battle.battle_tag, battle.turn, vals)
        return self.create_order(best)

    async def _search_async(self, battle):
        sync_tera_types(battle)
        if battle.reviving:
            return await self._revive_async(battle)
        me = battle.active_pokemon
        if me is None or battle.opponent_active_pokemon is None:
            log.warning("no search (%s turn %d): no active mon", battle.battle_tag, battle.turn)
            return None
        # a single legal option (must recharge, Struggle, one mon left to switch in): play it,
        # nothing to search or learn (the engine's state may even disagree, e.g. it lets a
        # recharging mon switch)
        moves, switches = battle.available_moves, battle.available_switches
        if len(moves) + len(switches) == 1 and not battle.can_tera:
            return self.create_order((moves or switches)[0])
        if battle.force_switch:
            kind = KIND_FORCED if me.fainted else KIND_PIVOT
        else:
            kind = KIND_MAIN
        t0 = time.time()
        full = self.rng.random() < self.full_frac
        n_worlds = self.worlds if full else self.fast_worlds
        names = self._opp_team_names(battle)
        last = self._foe_moves.get(battle.battle_tag)
        pending = last[1] if kind == KIND_PIVOT and last and last[0] == battle.turn else None
        states = [build_state(battle, self.belief, names, self.rng, move_beta=self.move_beta,
                                  damage_belief=self.damage_belief, arch_mix=self.arch_mix, foe_pending=pending)
                  for _ in range(n_worlds)]  # fmt: skip
        issues = request_mismatch(battle, states[0])
        if issues:
            self.mismatches += 1
            log.warning("request / engine state mismatch (%s turn %d): %s", battle.battle_tag,
                        battle.turn, issues)  # fmt: skip
        t1 = time.time()
        ctxs = net_context.contexts(battle, states, self.batcher.post)
        t2 = time.time()
        iters = self.full_iters if full else self.fast_iters
        looping = self.looping(battle)
        noise = (self.loop[4], self.noise[1]) if looping else self.noise
        fut = self.batcher.submit([s.to_string() for s in states], ctxs, iters,
                                  self.rng.randrange(1 << 30), noise)  # fmt: skip
        # safety net: a search must never hold a game forever
        res = await asyncio.wait_for(asyncio.wrap_future(fut), timeout=self.search_timeout)
        rec, n = res[0], res[1]
        if kind == KIND_MAIN:
            self._foe_moves[battle.battle_tag] = (battle.turn, foe_move_weights(states[0], rec))
        # the move: sampled from the visits, over options that have an order
        options = [(i, v) for i, v in enumerate(rec["visits"]) if v > 0 and rec["names"][i]]
        orders = {i: engine_move_to_order(self, battle, rec["names"][i]) for i, _ in options}
        options = [(i, v) for i, v in options if orders[i] is not None]
        if not options:
            log.warning("no order for the searched options (%s turn %d): %s; available moves %s, "
                        "switches %s", battle.battle_tag, battle.turn,
                        [(rec["names"][i], v) for i, v in enumerate(rec["visits"]) if v],
                        [m.id for m in battle.available_moves],
                        [m.species for m in battle.available_switches])  # fmt: skip
            return None
        tau = 1.0 if battle.turn <= self.temp_turns else self.temp_late
        if looping:
            tau = self.loop[3]
        if self.greedy:
            tau = 0.0
            slot = max(options, key=lambda o: o[1])[0]
        else:
            weights = [v ** (1 / tau) for _, v in options]
            slot = self.rng.choices([i for i, _ in options], weights=weights)[0]
        if not self.record or not order_is(orders[slot], rec["names"][slot]):
            # (an order other than the option searched: a single available move -- Struggle,
            # a locked move -- the engine did not see; the record would name a move not played)
            return orders[slot]
        reveal, ratings, turn, history = ctxs[0][:4]
        # F2: the root's posterior the network saw (x 255 rounded, as positions.py stores it)
        post = [round(v * 255) for v in ctxs[0][4]] if len(ctxs[0]) > 4 else None
        self.records.setdefault(battle.battle_tag, []).append({
            "side": battle.player_role, "turn": battle.turn, "kind": kind, "full": full,
            "worlds": n_worlds, "iterations": n, "seconds": round(time.time() - t0, 3),
            "t_worlds": round(t1 - t0, 4), "t_ctx": round(t2 - t1, 4),
            "t_search": round(time.time() - t2, 4), "tau": tau, "loop": looping,
            "state": states[0].to_string(), "reveal": list(reveal), "ratings": list(ratings),
            "ctx_turn": turn, "history": history, "slot": slot, "post": post,
            **{k: rec[k] for k in ("visits", "mean", "prior", "legal", "names", "q",
                                   "opp_visits", "opp_unmapped")},
        })  # fmt: skip
        self._record_request[battle.battle_tag] = self._n_requests.get(battle.battle_tag, 0)
        return orders[slot]

    def forget(self, tag: str) -> None:
        super().forget(tag)
        self._record_request.pop(tag, None)
        self._foe_moves.pop(tag, None)

    def _on_choice_rejected(self, tag: str) -> None:
        # the refused choice was not played: its record goes (the re-request makes a new one);
        # only if the last record answered the latest request (else the refused order was one
        # not recorded: a single option, a fallback). 2026-10-11: a switch out of an unseen
        # trap (Magnet Pull) was refused and the first record was the one converted
        recs = self.records.get(tag)
        if recs and self._record_request.get(tag) == self._n_requests.get(tag, 0):
            recs.pop()
            self._record_request.pop(tag, None)
            self.dropped_records += 1
