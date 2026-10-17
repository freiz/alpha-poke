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
		times_attacked: p.timesAttacked || 0, // (L163: Rage Fist)
		gender: p.gender || '', // (L163: 'M' / 'F' / 'N')
		// a Stellar tera's types already boosted once (L175)
		stellar_boosted: (p.stellarBoostedTypes || []).map(t => t.toLowerCase()),
		ability: p.ability || '',
		base_ability: p.baseAbility || '',
		types: p.getTypes(),
		pre_tera_types: p.getTypes(false, true), // what the engine keeps as types (STAB on them)
		base_types: p.baseSpecies.types,
		stats: p.storedStats,
		boosts: p.boosts,
		// (Perish Song: Showdown's perishsong with its turns left, the engine's perish<n>; L87)
		volatiles: Object.fromEntries(Object.entries(p.volatiles).map(([k, v]) =>
			[k === 'perishsong' ? `perish${v.duration}` : k, {duration: v.duration || 0, layers: v.layers || 0, counter: v.counter || 0,
				stat: v.bestStat || '', time: v.time || 0, true_duration: v.trueDuration || 0,
				num_consecutive: v.numConsecutive || 0, hp: v.hp || 0, move: v.move || '',
				// (a partial trap's source no longer in: it no longer traps and ends silently at
				// the residual; doc/engine-diff.md L170)
				source_out: !!(v.source && v.source.side !== p.side && !v.source.isActive)}])
			// Slow Start: a counter in the ability's state, the engine's volatile (L77)
			.concat(p.isActive && p.ability === 'slowstart' && p.abilityState.counter ?
				[['slowstart', {duration: p.abilityState.counter, layers: 0, counter: 0, stat: '',
					time: 0, true_duration: 0, num_consecutive: 0, hp: 0, move: ''}]] : [])
			// Protosynthesis / Quark Drive from Booster Energy (L141): the engine's volatile
			.concat(p.isActive && ((p.volatiles.protosynthesis || {}).fromBooster ||
				(p.volatiles.quarkdrive || {}).fromBooster) ?
				[['frombooster', {duration: 0, layers: 0, counter: 0, stat: '', time: 0,
					true_duration: 0, num_consecutive: 0, hp: 0, move: ''}]] : [])
			// its move failed last turn (Temper Flare / Stomping Tantrum; L115): the engine's volatile
			.concat(p.isActive && p.moveLastTurnResult === false ?
				[['lastmovefailed', {duration: 0, layers: 0, counter: 0, stat: '', time: 0,
					true_duration: 0, num_consecutive: 0, hp: 0, move: ''}]] : [])),
		moves: p.moveSlots.map(m => ({id: m.id, pp: m.pp, maxpp: m.maxpp, disabled: !!m.disabled})),
		terastallized: p.terastallized || '',
		transformed: !!p.transformed, // (L36: the engine's transform volatile)
		// its own stats, weight, moves and PP while transformed (L180: the engine's Pokemon::own)
		transform_backup: p.transformed ? [
			['atk', 'def', 'spa', 'spd', 'spe'].map(s => p.baseStoredStats[s]),
			p.baseSpecies.weighthg,
			p.baseMoveSlots.map(m => [m.id, m.pp]),
		] : null,
		tera_type: p.teraType || '',
		// the species' weight, as our state construction gives it: the engine applies Float Stone
		// (getWeight() would hide it)
		weight: p.weighthg / 10,
		nature: p.set.nature || 'Serious',
		active: !!p.isActive,
		// trapped for its request (true, or 'hidden': an ability's -- Shadow Tag, Magnet Pull --
		// that the request shows only as maybeTrapped; doc/engine-diff.md L177)
		trapped: !!p.trapped,
		// the engine's last_used_move: the move used since it came in, or none (Fake Out, Encore)
		last_move: p.lastMove ? p.lastMove.id : '',
		move_actions: p.activeMoveActions || 0,
		// Gen 9: Dauntless Shield / Intrepid Sword once per battle
		used_once: !!(p.shieldBoost || p.swordBoost || p.bondTriggered || p.syrupTriggered), // (L111: Battle Bond; L172: Supersweet Syrup)
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
	// the side used its Terastallization (a fainted tera mon loses its terastallized, the side's
	// canTerastallize stays null: doc/engine-diff.md L177)
	const tera_used = side.pokemon.some(p => p.terastallized || p.canTerastallize === null);
	return {id: side.id, active, mons, conditions, slot, request, request_json: req || null, tera_used};
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
		// the last move used in the battle (Copycat's; doc/engine-diff.md L167)
		last_move: battle.lastMove ? battle.lastMove.id : '',
		log: battle.log.slice(logFrom),
	}));
}

module.exports = {teamOf, monState, sideState, state};
