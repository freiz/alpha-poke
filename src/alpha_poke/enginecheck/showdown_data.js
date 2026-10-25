// Showdown's Gen 9 data tables (vendor/pokemon-showdown, built) for the data tests against
// poke-engine and poke-env (tests/test_engine_data.py, doc/engine-diff.md L8).
//
// Usage: node showdown_data.js <path to pokemon-showdown/dist/sim>
// stdout: one JSON object {"moves": [...], "species": [...], "types": [...], "items": [...]}
const {Dex} = require(process.argv[2]);
const dex = Dex.mod('gen9');
const legal = x => !x.isNonstandard || x.isNonstandard === 'Unobtainable';

const moves = dex.moves.all().filter(legal).map(m => ({
	id: m.id, type: m.type, accuracy: m.accuracy === true ? 'always' : m.accuracy, pp: m.pp,
	no_pp_boosts: !!m.noPPBoosts, ignore_evasion: !!m.ignoreEvasion,
	thaws_target: !!m.thawsTarget,
	category: m.category, basePower: m.basePower, priority: m.priority, target: m.target,
	flags: Object.keys(m.flags).sort(), drain: m.drain || null, recoil: m.recoil || null,
	heal: m.heal || null, status: m.status || null, volatileStatus: m.volatileStatus || null,
	sideCondition: m.sideCondition || null, boosts: m.boosts || null,
	self: m.self ? {chance: m.self.chance || 100, boosts: m.self.boosts || null,
		volatileStatus: m.self.volatileStatus || null} : null,
	selfBoost: m.selfBoost ? m.selfBoost.boosts : null,
	secondaries: (m.secondaries || []).map(s => ({chance: s.chance || 100, status: s.status || null,
		volatileStatus: s.volatileStatus || null, boosts: s.boosts || null,
		self: s.self ? {boosts: s.self.boosts || null} : null})),
	forceSwitch: !!m.forceSwitch, selfSwitch: !!m.selfSwitch,
	// (Sheer Force's onModifyMove / onBasePower: secondaries, or its boost without them)
	sheer_force: !!((m.secondaries && m.secondaries.length) || m.hasSheerForceBoost),
}));

const species = dex.species.all().filter(legal).map(s => ({
	id: s.id, types: s.types, baseStats: s.baseStats, weightkg: s.weightkg,
	abilities: Object.values(s.abilities).map(a => dex.abilities.get(a).id).sort(),
}));

// an item has a battle effect when it handles any event (a function: onResidual, onModifyAtk,
// ...; not the data fields onPlate, onDrive, ...) or holds a stat change (berries' onEat too)
const items = dex.items.all().filter(legal).map(i => ({
	id: i.id,
	effect: Object.entries(i).some(([k, v]) => /^on[A-Z]/.test(k) && typeof v === 'function') || !!i.boosts,
	berry: !!i.isBerry,
}));

const typeNames = dex.types.names().filter(t => t !== 'Stellar');
const types = [];
for (const a of typeNames) {
	for (const d of typeNames) {
		const mult = !dex.getImmunity(a, d) ? 0 : 2 ** dex.getEffectiveness(a, d);
		types.push([a, d, mult]);
	}
}
process.stdout.write(JSON.stringify({moves, species, types, items}));
