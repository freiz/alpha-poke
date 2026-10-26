// How often a protocol line appears in the last of the given turns over many simulator seeds:
// Showdown's chance of an event whose roll is not a randomChance (secondaries: King's Rock's
// flinch), for the dual-engine tests (doc/engine-diff.md).
//
// Usage: node chance_count.js <path to pokemon-showdown/dist/sim>
// stdin: {"p1": team, "p2": team, "turns": [[c1, c2], ...], "line": substring, "n": seeds}
// stdout: {"hits": k, "n": n, "error": null}
const crypto = require('crypto');
const {Battle, Teams} = require(process.argv[2]);
const {teamOf} = require('./showdown_state.js');

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const c = JSON.parse(input);
	let hits = 0;
	const logs = [];
	let error = null;
	try {
		for (let i = 0; i < c.n; i++) {
			// a sodium seed from a hash (2026-10-25): Showdown's "gen5," seeds are four 4-digit hex
			// fields run together -- "gen5,i,j,..." ones parse to near-identical, correlated seeds (a
			// 28.75% flinch for King's Rock's 10%; a resampled freeze's thaw 39% for its 20%)
			const hex = crypto.createHash('sha256').update(`chance:${i}`).digest('hex').slice(0, 32);
			const battle = new Battle({formatid: 'gen9customgame', seed: `sodium,${hex}`});
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
			if (c.lines) logs.push(battle.log.slice(from));
			else if (battle.log.slice(from).some(x => x.includes(c.line))) hits++;
		}
	} catch (e) {
		error = String(e && e.stack || e);
	}
	process.stdout.write(JSON.stringify({hits, n: c.n, logs, error}));
});
