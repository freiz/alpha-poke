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
const {PRNG} = require(process.argv[2] + '/prng');
const {state} = require('./showdown_state.js');

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const out = [];
	for (const c of JSON.parse(input)) {
		const states = [];
		let error = null;
		try {
			const raw = JSON.stringify(c.battle); // (deserializeBattle takes the object apart: a copy each time)
			for (let i = 0; i < c.n; i++) {
				// (well spread seeds: neighbouring small ones give correlated first rolls -- chance_count.js)
				const h = k => (Math.imul(i + 1 + (c.salt || 0) * 7919, 0x9E3779B1 + k * 0x85EBCA6B) >>> 16) & 0xFFFF;
				const battle = State.deserializeBattle(JSON.parse(raw));
				battle.prng = new PRNG(`gen5,${h(1)},${h(2)},${h(3)},${h(4)}`);
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
	process.stdout.write(JSON.stringify(out));
});
