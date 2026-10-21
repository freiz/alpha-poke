// A whole battle in Showdown's simulator with random legal choices, for the full-information
// engine differential (doc/engine-diff.md): the truth at every decision point and the choices.
//
// Usage: node random_battle.js <path to pokemon-showdown/dist/sim>
// stdin: one JSON object {"format": "gen9customgame", "seed": "gen5,...", "choice_seed": n,
//        "p1": team, "p2": team, "max_turns": n, "switch_p": share of switches when a move is
//        possible, "tera_p": share of terastallized moves when possible}
// stdout: {"steps": [{"state": state (showdown_state.js), "choices": {"p1": c, "p2": c}}, ...],
//          "error": null}: a step per decision point (a turn's start, a forced switch, a pivot);
//          c = {"choice": Showdown's, "engine": the engine's name ("knockoff", "earthquake-tera",
//          "none" for a recharge, a species id for a switch), "kind": "move" / "switch"}; the
//          last step has the final state and no choices. "serialize_every": k -- every k-th
//          step with both sides choosing also has "battle", Showdown's whole battle serialized
//          (State.serializeBattle: showdown_claims.js plays from it)
const {Battle, Teams} = require(process.argv[2]);
const {teamOf, state} = require('./showdown_state.js');
const {maxDamages} = require('./showdown_damage.js');
const {State} = require(process.argv[2] + '/state');

function rng(seed) { // mulberry32
	let a = seed >>> 0;
	return () => {
		a = (a + 0x6D2B79F5) >>> 0;
		let t = a;
		t = Math.imul(t ^ (t >>> 15), t | 1);
		t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

function pick(xs, r) {
	return xs[Math.floor(r() * xs.length)];
}

const CALLERS = ['metronome', 'copycat', 'assist', 'mefirst', 'naturepower', 'mirrormove'];
function calledLock(p, id) {
	if (!p || p.moveSlots.some(m => m.id === id)) return null;
	const caller = p.moveSlots.find(m => CALLERS.includes(m.id));
	return caller ? caller.id : null;
}

function choose(side, req, r, c) {
	const pokes = req.side.pokemon;
	const switches = [];
	pokes.forEach((p, i) => {
		if (!p.active && !p.condition.endsWith(' fnt')) switches.push(i);
	});
	const toSwitch = i => ({choice: `switch ${i + 1}`, engine: side.pokemon[i].species.id, kind: 'switch'});
	// Revival Blessing's pick: a fainted one (doc/engine-diff.md L177; the battle used to break off)
	if (req.forceSwitch && pokes.some(p => p.reviving)) {
		const fainted = [];
		pokes.forEach((p, i) => { if (p.condition.endsWith(' fnt')) fainted.push(i); });
		if (fainted.length) return toSwitch(pick(fainted, r));
	}
	if (req.forceSwitch) return switches.length ? toSwitch(pick(switches, r)) : {choice: 'pass', engine: 'none', kind: 'pass'};
	const act = req.active[0];
	const moves = [];
	act.moves.forEach((m, i) => {
		if (!m.disabled) moves.push([i, m.id]);
	});
	const canSwitch = switches.length && !act.trapped && !act.maybeTrapped;
	if (canSwitch && (!moves.length || r() < c.switch_p)) return toSwitch(pick(switches, r));
	if (!moves.length) return {choice: 'default', engine: 'none', kind: 'move'};
	const [i, id] = pick(moves, r);
	if (id === 'recharge') return {choice: `move ${i + 1}`, engine: 'none', kind: 'move'};
	// (L224: a charge move a calling move started, not its own: the engine's caller slot)
	const called = calledLock(side.active[0], id);
	if (called) return {choice: `move ${i + 1}`, engine: called, kind: 'move'};
	if (act.canTerastallize && r() < c.tera_p) {
		return {choice: `move ${i + 1} terastallize`, engine: `${id}-tera`, kind: 'move'};
	}
	return {choice: `move ${i + 1}`, engine: id, kind: 'move'};
}

let input = '';
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
	const c = JSON.parse(input);
	const steps = [];
	let error = null;
	try {
		const opts = {formatid: c.format || 'gen9customgame', strictChoices: true};
		if (c.seed) opts.seed = c.seed;
		const battle = new Battle(opts);
		battle.setPlayer('p1', {name: 'p1', team: Teams.pack(teamOf(c.p1))});
		battle.setPlayer('p2', {name: 'p2', team: Teams.pack(teamOf(c.p2))});
		if (battle.p1.activeRequest && battle.p1.activeRequest.teamPreview) {
			battle.makeChoices('default', 'default');
		}
		const r = rng(c.choice_seed || 1);
		let from = 0;
		while (!battle.ended && battle.turn <= (c.max_turns || 100)) {
			const snap = state(battle, from);
			from = battle.log.length;
			const choices = {};
			for (const side of [battle.p1, battle.p2]) {
				const req = side.activeRequest;
				if (!req || req.wait) continue;
				choices[side.id] = choose(side, req, r, c);
			}
			if (!Object.keys(choices).length) break;
			const step = {state: snap, choices};
			if (c.damage_probe && choices.p1 && choices.p2 && choices.p1.kind !== 'pass') step.damage = maxDamages(battle);
			if (c.serialize_every && choices.p1 && choices.p2 && steps.length % c.serialize_every === 0) {
				step.battle = State.serializeBattle(battle);
			}
			steps.push(step);
			for (const [sid, ch] of Object.entries(choices)) battle.choose(sid, ch.choice);
		}
		steps.push({state: state(battle, from), choices: {}});
	} catch (e) {
		error = String(e && e.stack || e);
	}
	process.stdout.write(JSON.stringify({steps, error}));
});
