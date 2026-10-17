// How often a protocol line appears in the last of the given turns over many simulator seeds:
// Showdown's chance of an event whose roll is not a randomChance (secondaries: King's Rock's
// flinch), for the dual-engine tests (doc/engine-diff.md).
//
// Usage: node chance_count.js <path to pokemon-showdown/dist/sim>
// stdin: {"p1": team, "p2": team, "turns": [[c1, c2], ...], "line": substring, "n": seeds}
// stdout: {"hits": k, "n": n, "error": null}
const {Battle, Teams} = require(process.argv[2]);
const {teamOf} = require('./showdown_state.js');

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const c = JSON.parse(input);
	let hits = 0;
	let error = null;
	try {
		for (let i = 0; i < c.n; i++) {
			// well spread seeds: neighbouring small ones give correlated first rolls (a 28.75% flinch
			// for King's Rock's 10% with gen5,i,i+7,...)
			const h = k => (Math.imul(i + 1, 0x9E3779B1 + k * 0x85EBCA6B) >>> 16) & 0xFFFF;
			const battle = new Battle({formatid: 'gen9customgame', seed: `gen5,${h(1)},${h(2)},${h(3)},${h(4)}`});
			battle.setPlayer('p1', {name: 'p1', team: Teams.pack(teamOf(c.p1))});
			battle.setPlayer('p2', {name: 'p2', team: Teams.pack(teamOf(c.p2))});
			if (battle.p1.activeRequest && battle.p1.activeRequest.teamPreview) {
				battle.makeChoices('default', 'default');
			}
			let from = 0;
			for (const [a, b] of c.turns) {
				from = battle.log.length;
				battle.makeChoices(a, b);
			}
			if (battle.log.slice(from).some(x => x.includes(c.line))) hits++;
		}
	} catch (e) {
		error = String(e && e.stack || e);
	}
	process.stdout.write(JSON.stringify({hits, n: c.n, error}));
});
