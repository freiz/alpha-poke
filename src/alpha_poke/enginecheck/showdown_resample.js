// One recorded step played again under many seeds: Showdown's own distribution of a turn's
// outcomes, for the engine's branch probabilities (enginecheck.distdiff; 2026-10-25 review: the
// differential matched each step's one outcome to some branch -- a Will-O-Wisp's 85% made 1%
// still matched its hits).
//
// Usage: node showdown_resample.js <path to pokemon-showdown/dist/sim>
// stdin: [{"battle": serialized (random_battle.js "serialize_every"), "choices": {"p1": c,
//          "p2": c} (Showdown's), "n": seeds, "salt": n}, ...]
// stdout: [{"states": [state (showdown_state.js) after the turn, ...], "error": null}, ...]
const {State} = require(process.argv[2] + '/state');
const crypto = require('crypto');
const {PRNG} = require(process.argv[2] + '/prng');
const {state} = require('./showdown_state.js');

function main(cases) {
	const out = [];
	for (const c of cases) {
		const states = [];
		let error = null;
		try {
			const raw = JSON.stringify(c.battle); // (deserializeBattle takes the object apart: a copy each time)
			for (let i = 0; i < c.n; i++) {
				// (a sodium seed from a hash: Showdown's "gen5," seeds are four 4-digit hex fields run
				// together -- "gen5,1,2,3,4"-like ones parse to near-identical, correlated seeds; the
				// turn's first roll, a freeze's thaw, came out 39% for its 20%)
				const hex = crypto.createHash('sha256').update(`${c.salt || 0}:${i}`).digest('hex').slice(0, 32);
				const battle = State.deserializeBattle(JSON.parse(raw));
				battle.prng = new PRNG(`sodium,${hex}`);
				const from = battle.log.length;
				for (const sid of ['p1', 'p2']) {
					if (c.choices[sid]) battle.choose(sid, c.choices[sid]);
				}
				states.push(state(battle, from));
			}
		} catch (e) {
			error = String(e && e.stack || e);
		}
		out.push({states, error});
	}
	return out;
}

module.exports = {main};
// (as a command: one JSON on stdin, one on stdout; showdown_server.js calls main() directly)
if (require.main === module) {
	let input = '';
	process.stdin.on('data', d => { input += d; });
	process.stdin.on('end', () => process.stdout.write(JSON.stringify(main(JSON.parse(input)))));
}
