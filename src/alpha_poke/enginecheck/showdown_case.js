// One battle scenario in Showdown's simulator (vendor/pokemon-showdown, built), for the
// dual-engine unit tests (doc/engine-diff.md): the state after the setup and after every turn.
//
// Usage: node showdown_case.js <path to pokemon-showdown/dist/sim>
// stdin: one JSON object {"format": "gen9customgame", "seed": "gen5,..." | null,
//        "force_random": true | false | null (Battle's forceRandomChance: every chance roll
//        succeeds / fails), "p1": team, "p2": team (Showdown export text or a list of sets),
//        "turns": [[p1 choice, p2 choice], ...] ("move defog", "switch 2", "move 1 terastallize");
//        stops early when the battle ends or waits for a forced switch the turns do not give}
// stdout: one JSON object {"states": [state after setup, after turn 1, ...], "error": null}
// A state: {"turn", "ended", "winner", "field": {...}, "sides": [side p1, side p2], "log": [...]}
// with each side's mons in TEAM ORDER (the order of the input team, as the engine keeps it).
const {Battle, Teams} = require(process.argv[2]);

function teamOf(x) {
	return typeof x === 'string' ? Teams.import(x) : x;
}

function monState(p, side) {
	return {
		slot: side.team.indexOf(p.set),
		species: p.species.id,
		level: p.level,
		hp: p.hp,
		maxhp: p.maxhp,
		fainted: !!p.fainted,
		status: p.status || '',
		status_state: {stage: p.statusState.stage || 0, time: p.statusState.time || 0,
			startTime: p.statusState.startTime || 0},
		item: p.item || '',
		ability: p.ability || '',
		base_ability: p.baseAbility || '',
		types: p.getTypes(),
		base_types: p.baseSpecies.types,
		stats: p.storedStats,
		boosts: p.boosts,
		volatiles: Object.fromEntries(Object.entries(p.volatiles).map(([k, v]) =>
			[k, {duration: v.duration || 0, layers: v.layers || 0, counter: v.counter || 0,
				stat: v.bestStat || ''}])),
		moves: p.moveSlots.map(m => ({id: m.id, pp: m.pp, maxpp: m.maxpp, disabled: !!m.disabled})),
		terastallized: p.terastallized || '',
		tera_type: p.teraType || '',
		weight: p.getWeight() / 10,
		active: !!p.isActive,
		// Gen 9: Dauntless Shield / Intrepid Sword once per battle
		used_once: !!(p.shieldBoost || p.swordBoost),
	};
}

function sideState(side) {
	const mons = side.pokemon.map(p => monState(p, side)).sort((a, b) => a.slot - b.slot);
	const active = side.active[0] ? side.team.indexOf(side.active[0].set) : -1;
	const conditions = Object.fromEntries(Object.entries(side.sideConditions).map(([k, v]) =>
		[k, {layers: v.layers || 0, duration: v.duration || 0}]));
	// Future Sight / Doom Desire: a condition of the target's slot, from a mon of the other side
	const slot = Object.fromEntries(Object.entries(side.slotConditions[0] || {}).map(([k, v]) =>
		[k, {duration: v.duration || 0, ending_turn: v.endingTurn || 0,
			source: v.source && v.source.side ? v.source.side.team.indexOf(v.source.set) : -1}]));
	const req = side.activeRequest;
	const request = !req ? 'none' : req.wait ? 'wait' : req.forceSwitch ? 'switch' :
		req.teamPreview ? 'teampreview' : 'move';
	// the request the player's client gets (for rebuilding the state as we do in play)
	return {id: side.id, active, mons, conditions, slot, request, request_json: req || null};
}

function state(battle, logFrom) {
	const f = battle.field;
	// a deep copy: the battle's objects (boosts, ...) keep changing
	return JSON.parse(JSON.stringify({
		turn: battle.turn,
		ended: battle.ended,
		winner: battle.winner || '',
		field: {
			weather: f.weather || '', weather_duration: f.weatherState.duration || 0,
			terrain: f.terrain || '', terrain_duration: f.terrainState.duration || 0,
			pseudo: Object.fromEntries(Object.entries(f.pseudoWeather).map(([k, v]) =>
				[k, v.duration || 0])),
		},
		sides: [sideState(battle.p1), sideState(battle.p2)],
		log: battle.log.slice(logFrom),
	}));
}

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const c = JSON.parse(input);
	const states = [];
	let error = null;
	try {
		const opts = {formatid: c.format || 'gen9customgame', strictChoices: true};
		if (c.seed) opts.seed = c.seed;
		if (c.force_random !== null && c.force_random !== undefined) opts.forceRandomChance = c.force_random;
		const battle = new Battle(opts);
		battle.setPlayer('p1', {name: 'p1', team: Teams.pack(teamOf(c.p1))});
		battle.setPlayer('p2', {name: 'p2', team: Teams.pack(teamOf(c.p2))});
		if (battle.p1.activeRequest && battle.p1.activeRequest.teamPreview) {
			battle.makeChoices('default', 'default');
		}
		let from = 0;
		states.push(state(battle, from));
		from = battle.log.length;
		for (const [a, b] of c.turns || []) {
			// a forced switch pending (a faint) and the given choices are not for it: stop here
			const forced = [battle.p1, battle.p2].some(sd => sd.activeRequest && sd.activeRequest.forceSwitch);
			if (battle.ended || (forced && !(String(a).startsWith('switch') || String(b).startsWith('switch')))) break;
			battle.makeChoices(a, b);
			states.push(state(battle, from));
			from = battle.log.length;
		}
	} catch (e) {
		error = String(e && e.stack || e);
	}
	process.stdout.write(JSON.stringify({states, error}));
});
