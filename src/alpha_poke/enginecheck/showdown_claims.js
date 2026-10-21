// The network inputs' claims played out in Showdown's simulator itself (the feature-claim check,
// doc/results.md "特征断言检验"; scripts/check_feature_claims_sd.py): a battle restored from its
// serialization (random_battle.js "serialize_every") under the claims' assumptions -- every move
// hits; nothing by chance happens (randomChance true only when sure: no chance crit, secondary,
// full paralysis, confusion hit, Quick Claw, Static, ...; a sure crit, a 100% secondary stay);
// each side's damage rolls fixed to its min (85%) or max and its multi-hit moves to their fewest
// or most hits -- and the given turns. (Not fixed: speed ties, sleep turns: the check skips them.)
//
// Usage: node showdown_claims.js <path to pokemon-showdown/dist/sim>
// stdin: [{"battle": serialized, "rolls": {"p1": "min" | "max", "p2": ...},
//          "noop": "p1" | "p2" | null (that side's active only uses Splash: a target doing
//          nothing), "turns": [[p1 choice, p2 choice], ...]}, ...] -- a choice "move <id>",
//          "switch <team slot>" (showdown_state.js's order: Showdown's order of a side changes
//          with switches),
//          "log": true for each turn's log lines too,
//          "pass" (when that side has nothing to choose)
// stdout: [{"turns": [{"hp": {"p1": {team slot: hp}, "p2": ...}, "moves": [side id of each move
//          line in order], "hp_moves": the HPs before the end of the turn, "ended": bool}, ...],
//          "error": null}, ...]: after each turn played;
//          stops when the battle ends or waits for a choice the turns do not give
const {State} = require(process.argv[2] + '/state');

function rules(battle, rolls) {
	const tr = battle.trunc;
	let side = null;
	const getDamage = battle.actions.getDamage;
	battle.actions.getDamage = function (source, target, move, suppress) {
		side = source.side.id;
		return getDamage.call(this, source, target, move, suppress);
	};
	battle.randomizer = function (d) {
		return rolls[side] === 'min' ? tr(tr(d * 85) / 100) : d;
	};
	battle.randomChance = (n, d) => n >= d;
	battle.onEvent('Accuracy', battle.format, -100, () => true);
	battle.onEvent('ModifyMove', battle.format, -100, function (move, pokemon) {
		// (a secondary rolls random(100), not randomChance: one under 100% taken off)
		if (move.secondaries) move.secondaries = move.secondaries.filter(x => x.chance === undefined || x.chance >= 100);
		const sid = pokemon && pokemon.side && pokemon.side.id;
		if (Array.isArray(move.multihit)) {
			let [lo, hi] = move.multihit;
			if (pokemon && pokemon.hasItem && pokemon.hasItem('loadeddice') && hi === 5) lo = 4;
			move.multihit = rolls[sid] === 'min' ? lo : hi;
		}
	});
}

// each side's HPs by team slot (showdown_state.js's order: a species changes with a forme)
function hpOf(battle) {
	const out = {};
	for (const side of [battle.p1, battle.p2]) {
		out[side.id] = {};
		for (const p of side.pokemon) out[side.id][side.team.indexOf(p.set)] = p.hp;
	}
	return out;
}

function choiceFor(battle, sid, text) {
	if (!text || text === 'pass') return 'pass';
	if (text.startsWith('switch ')) {
		const want = Number(text.slice(7));
		const side = battle[sid];
		const i = side.pokemon.findIndex(p => !p.isActive && side.team.indexOf(p.set) === want);
		if (i < 0) throw new Error(`no team slot ${want} to switch to`);
		return `switch ${i + 1}`;
	}
	return text;
}

function run(c) {
	const battle = State.deserializeBattle(c.battle);
	rules(battle, c.rolls || {p1: 'max', p2: 'max'});
	if (c.noop) {
		const p = battle[c.noop].active[0];
		const slot = {id: 'splash', move: 'Splash', pp: 64, maxpp: 64, target: 'self', disabled: false, used: false};
		p.moveSlots = [Object.assign({}, slot)];
		p.baseMoveSlots = [Object.assign({}, slot)];
	}
	// the HPs as the end of the turn starts (its residual action)
	let pre = null;
	const runAction = battle.runAction;
	battle.runAction = function (action) {
		if (action.choice === 'residual') pre = hpOf(this);
		return runAction.call(this, action);
	};
	const turns = [];
	for (const [a, b] of c.turns) {
		if (battle.ended) break;
		// (a mon down, its side to switch: the exchange is over)
		if ([battle.p1, battle.p2].some(sd => sd.activeRequest && sd.activeRequest.forceSwitch) && turns.length) break;
		const need = [battle.p1, battle.p2].map(s => s.activeRequest && !s.activeRequest.wait);
		const ca = choiceFor(battle, 'p1', a), cb = choiceFor(battle, 'p2', b);
		if ((need[0] && ca === 'pass') || (need[1] && cb === 'pass')) break;
		const from = battle.log.length;
		pre = null;
		if (need[0]) battle.choose('p1', ca);
		if (need[1]) battle.choose('p2', cb);
		const moves = battle.log.slice(from).filter(l => l.startsWith('|move|')).map(l => l.split('|')[2].slice(0, 2));
		const hp = hpOf(battle);
		const t = {hp, hp_moves: pre || hp, moves, ended: battle.ended};
		if (c.log) t.log = battle.log.slice(from);
		turns.push(t);
	}
	return turns;
}

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const out = [];
	for (const c of JSON.parse(input)) {
		try {
			out.push({turns: run(c), error: null});
		} catch (e) {
			out.push({turns: [], error: String(e && e.stack || e).slice(0, 500)});
		}
	}
	process.stdout.write(JSON.stringify(out));
});
