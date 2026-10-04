// Raw Showdown simulator throughput: BattleStream driven in-process (no websocket, no server).
// Random-vs-random Gen9 OU with teams from configs/teams/*.txt.
//
// Usage: node scripts/bench_battlestream.js [battles=200] [format=gen9ou]
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const sim = require(path.join(root, 'vendor/pokemon-showdown/dist/sim'));
const {RandomPlayerAI} = require(path.join(root, 'vendor/pokemon-showdown/dist/sim/tools/random-player-ai'));

const nBattles = parseInt(process.argv[2] || '200');
const format = process.argv[3] || 'gen9ou';

const teamDir = path.join(root, 'configs/teams');
const teams = fs.readdirSync(teamDir).filter(f => f.endsWith('.txt')).map(f =>
	sim.Teams.pack(sim.Teams.import(fs.readFileSync(path.join(teamDir, f), 'utf8'))));

async function playOne(seed) {
	const streams = sim.getPlayerStreams(new sim.BattleStream());
	const pick = i => teams[(seed + i) % teams.length];
	const p1 = new RandomPlayerAI(streams.p1, {seed: [seed, 1, 2, 3]});
	const p2 = new RandomPlayerAI(streams.p2, {seed: [seed, 4, 5, 6]});
	void p1.start();
	void p2.start();
	let turns = 0;
	const done = (async () => {
		for await (const chunk of streams.omniscient) {
			for (const line of chunk.split('\n')) if (line.startsWith('|turn|')) turns = parseInt(line.slice(6));
		}
	})();
	void streams.omniscient.write(`>start ${JSON.stringify({formatid: format, seed: [seed, 7, 8, 9]})}\n` +
		`>player p1 ${JSON.stringify({name: 'A', team: pick(0)})}\n` +
		`>player p2 ${JSON.stringify({name: 'B', team: pick(1)})}`);
	await done;
	return turns;
}

(async () => {
	let totalTurns = 0;
	const t0 = process.hrtime.bigint();
	for (let i = 0; i < nBattles; i++) totalTurns += await playOne(i + 1);
	const dt = Number(process.hrtime.bigint() - t0) / 1e9;
	console.log(`${nBattles} battles, ${totalTurns} turns in ${dt.toFixed(1)}s -> ` +
		`${(nBattles / dt).toFixed(1)} battles/s, ${(totalTurns / dt).toFixed(0)} turns/s ` +
		`(${(totalTurns / nBattles).toFixed(1)} turns/battle) [single process]`);
})();
