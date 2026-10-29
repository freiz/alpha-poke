// A persistent node process for the Showdown helper scripts (2026-10-28; enginecheck.node_script):
// the simulator is loaded once, each request runs one script's main() -- a fresh `node <script>`
// per call (most of the unit tests' time) only when this is off (ALPHA_NODE_SERVER=0) or broken.
//
// Usage: node showdown_server.js <path to pokemon-showdown/dist/sim>
// stdin: one JSON per line {"script": "showdown_case" | "crit_ratio" | ..., "input": its input}
// stdout: one JSON per line {"out": main(input), "server_error": null}, or {"out": null,
//         "server_error": "..."} when the script could not run at all (its own errors stay in
//         its output, as from the command line)
// The scripts read the simulator's path from process.argv[2]: the same here.
const path = require('path');
const readline = require('readline');

const scripts = {};
const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
rl.on('line', line => {
	let res;
	try {
		const req = JSON.parse(line);
		if (!/^[a-z_]+$/.test(req.script)) throw new Error(`bad script name ${req.script}`);
		const mod = scripts[req.script] || (scripts[req.script] = require(path.join(__dirname, `${req.script}.js`)));
		res = {out: mod.main(req.input), server_error: null};
	} catch (e) {
		res = {out: null, server_error: String(e && e.stack || e).slice(0, 2000)};
	}
	process.stdout.write(JSON.stringify(res) + '\n');
});
