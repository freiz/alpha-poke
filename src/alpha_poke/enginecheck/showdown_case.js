// One battle scenario in Showdown's simulator (vendor/pokemon-showdown, built), for the
// dual-engine unit tests (doc/engine-diff.md): the state after the setup and after every turn.
//
// Usage: node showdown_case.js <path to pokemon-showdown/dist/sim>
// stdin: one JSON object {"format": "gen9customgame", "seed": "gen5,..." | null,
//        "force_random": true | false | null (Battle's forceRandomChance: every chance roll
//        succeeds / fails), "p1": team, "p2": team (Showdown export text or a list of sets),
//        "turns": [[p1 choice, p2 choice], ...] ("move defog", "switch 2", "move 1 terastallize");
//        stops early when the battle ends or waits for a forced switch the turns do not give;
//        "damage_probe": each state also has "damage", showdown_damage.js's max damages}
// stdout: one JSON object {"states": [state after setup, after turn 1, ...], "error": null}
// A state: {"turn", "ended", "winner", "field": {...}, "sides": [side p1, side p2], "log": [...]}
// with each side's mons in TEAM ORDER (the order of the input team, as the engine keeps it).
const {Battle, Teams} = require(process.argv[2]);

const {teamOf, state} = require('./showdown_state.js');
const {maxDamages} = require('./showdown_damage.js');

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
		const snap = () => c.damage_probe ? {...state(battle, from), damage: maxDamages(battle)} : state(battle, from);
		states.push(snap());
		from = battle.log.length;
		for (const [a, b] of c.turns || []) {
			// a forced switch pending (a faint) and the given choices are not for it: stop here
			const forced = [battle.p1, battle.p2].some(sd => sd.activeRequest && sd.activeRequest.forceSwitch);
			if (battle.ended || (forced && !(String(a).startsWith('switch') || String(b).startsWith('switch')))) break;
			battle.makeChoices(a, b);
			states.push(snap());
			from = battle.log.length;
		}
	} catch (e) {
		error = String(e && e.stack || e);
	}
	process.stdout.write(JSON.stringify({states, error}));
});
