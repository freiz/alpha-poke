// Showdown's critical-hit stage of p1's active's moves against p2's active (its own
// ModifyCritRatio event, clamped as getDamage does), after the given turns: the dual-engine tests
// of crit chances (doc/engine-diff.md), which one battle's roll cannot show.
//
// Usage: node crit_ratio.js <path to pokemon-showdown/dist/sim>
// stdin: {"p1": team, "p2": team, "turns": [[c1, c2], ...], "seed": "gen5,..."}
// stdout: {"stages": {move id: stage 0-4}, "accuracy": {move id: % or true}, "error": null}
// (accuracy: after Showdown's ModifyAccuracy event, as if p2 had moved: Zoom Lens counts)
const {Battle, Teams} = require(process.argv[2]);
const {teamOf} = require('./showdown_state.js');

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const c = JSON.parse(input);
	const stages = {};
	const accuracy = {};
	let error = null;
	try {
		const battle = new Battle({formatid: 'gen9customgame', seed: c.seed || 'gen5,1,2,3,4'});
		battle.setPlayer('p1', {name: 'p1', team: Teams.pack(teamOf(c.p1))});
		battle.setPlayer('p2', {name: 'p2', team: Teams.pack(teamOf(c.p2))});
		if (battle.p1.activeRequest && battle.p1.activeRequest.teamPreview) {
			battle.makeChoices('default', 'default');
		}
		for (const [a, b] of c.turns || []) battle.makeChoices(a, b);
		const source = battle.p1.active[0];
		const target = battle.p2.active[0];
		for (const slot of source.moveSlots) {
			const move = battle.dex.getActiveMove(slot.id);
			let ratio = battle.runEvent('ModifyCritRatio', source, target, move, move.critRatio || 0);
			stages[slot.id] = Math.max(0, Math.min(4, ratio));
			const acc = move.accuracy;
			accuracy[slot.id] = acc === true ? true : battle.runEvent('ModifyAccuracy', target, source, move, acc);
		}
	} catch (e) {
		error = String(e && e.stack || e);
	}
	process.stdout.write(JSON.stringify({stages, accuracy, error}));
});
