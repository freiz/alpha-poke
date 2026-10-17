// The damage probe (doc/engine-diff.md, the damage calculation differential): Showdown's own
// getDamage on a copy of a battle, for scripts/check_damage_calc.py and the dual-engine tests.
const {State} = require(process.argv[2] + '/state');

// Showdown's max damage (no crit, the 100% roll) of each move of each active against the other,
// on a copy of the battle (the damage probe: scripts/check_damage_calc.py); null for a status move
// or no damage
function maxDamages(battle) {
	const out = {};
	for (const [i, side] of [battle.p1, battle.p2].entries()) {
		const src = side.active[0];
		if (!src || src.fainted) continue;
		out[side.id] = {};
		for (const slot of src.moveSlots) {
			let dmg = null;
			try {
				const b = State.deserializeBattle(State.serializeBattle(battle));
				b.randomizer = d => d;
				const s = b.sides[i].active[0];
				const t = b.sides[1 - i].active[0];
				const move = b.dex.getActiveMove(slot.id);
				if (move.category !== 'Status') {
					move.willCrit = false;
					b.activeMove = move;
					b.activePokemon = s;
					b.activeTarget = t;
					b.singleEvent('ModifyType', move, null, s, t, move, move);
					b.runEvent('ModifyType', s, t, move, move);
					b.singleEvent('ModifyMove', move, null, s, t, move, move);
					b.runEvent('ModifyMove', s, t, move, move);
					// Libero / Protean (onPrepareHit), the target's immunities by ability
					// (Water Absorb, Flash Fire, ...: onTryHit) and the move's own onTry
					// (Poltergeist): 0 when they stop it
					b.singleEvent('PrepareHit', move, {}, t, s, move);
					b.runEvent('PrepareHit', s, t, move);
					const ok = b.singleEvent('Try', move, null, s, t, move) !== false &&
						b.runEvent('TryHit', t, s, move) &&
						b.singleEvent('TryHit', move, {}, t, s, move) !== false;
					const d = ok ? b.actions.getDamage(s, t, move) : 0;
					dmg = typeof d === 'number' ? d : d === false ? 0 : null;
				}
			} catch (e) {
				dmg = 'error: ' + String(e).slice(0, 80);
			}
			out[side.id][slot.id] = dmg;
		}
	}
	return out;
}

module.exports = {maxDamages};
