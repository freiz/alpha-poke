// The state dump of a Showdown battle for the dual-engine tests (doc/engine-diff.md): shared by
// showdown_case.js (a given scenario) and random_battle.js (random choices).
const {Teams} = require(process.argv[2]);

function teamOf(x) {
	return typeof x === 'string' ? Teams.import(x) : x;
}

function monState(p, side) {
	return {
		slot: side.team.indexOf(p.set),
		// (a transformed mon: its own species, the engine keeps it; L36)
		species: p.transformed ? p.baseSpecies.id : p.species.id,
		level: p.level,
		hp: p.hp,
		maxhp: p.maxhp,
		fainted: !!p.fainted,
		status: p.status || '',
		status_state: {stage: p.statusState.stage || 0, time: p.statusState.time || 0,
			startTime: p.statusState.startTime || 0,
			// Rest's sleep: the only one set by the sleeper itself (statusState keeps the source
			// Pokemon, not the effect: the effect's id was always empty)
			source: p.statusState.source === p ? 'rest' : ''},
		item: p.item || '',
		last_item: p.lastItem || '', // (L57: Harvest's berry)
		ability: p.ability || '',
		base_ability: p.baseAbility || '',
		types: p.getTypes(),
		pre_tera_types: p.getTypes(false, true), // what the engine keeps as types (STAB on them)
		base_types: p.baseSpecies.types,
		stats: p.storedStats,
		boosts: p.boosts,
		volatiles: Object.fromEntries(Object.entries(p.volatiles).map(([k, v]) =>
			[k, {duration: v.duration || 0, layers: v.layers || 0, counter: v.counter || 0,
				stat: v.bestStat || '', time: v.time || 0, true_duration: v.trueDuration || 0,
				num_consecutive: v.numConsecutive || 0, hp: v.hp || 0, move: v.move || ''}])
			// Slow Start: a counter in the ability's state, the engine's volatile (L77)
			.concat(p.isActive && p.ability === 'slowstart' && p.abilityState.counter ?
				[['slowstart', {duration: p.abilityState.counter, layers: 0, counter: 0, stat: '',
					time: 0, true_duration: 0, num_consecutive: 0, hp: 0, move: ''}]] : [])),
		moves: p.moveSlots.map(m => ({id: m.id, pp: m.pp, maxpp: m.maxpp, disabled: !!m.disabled})),
		terastallized: p.terastallized || '',
		transformed: !!p.transformed, // (L36: the engine's transform volatile)
		tera_type: p.teraType || '',
		// the species' weight, as our state construction gives it: the engine applies Float Stone
		// (getWeight() would hide it)
		weight: p.weighthg / 10,
		nature: p.set.nature || 'Serious',
		active: !!p.isActive,
		// the engine's last_used_move: the move used since it came in, or none (Fake Out, Encore)
		last_move: p.lastMove ? p.lastMove.id : '',
		move_actions: p.activeMoveActions || 0,
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
		[k, {duration: v.duration || 0, ending_turn: v.endingTurn || 0, hp: v.hp || 0,
			starting_turn: v.startingTurn || 0,
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

module.exports = {teamOf, monState, sideState, state};
