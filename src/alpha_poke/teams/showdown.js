// Canonicalize and validate Showdown-format teams with the local Showdown checkout
// (vendor/pokemon-showdown, built). Used by alpha_poke.teams.validate.
//
// Usage: node showdown.js <path to pokemon-showdown/dist/sim> <format>
// stdin: one JSON object per line {"id": ..., "text": <Showdown export>}
// stdout: one JSON object per line {"id", "n" (sets parsed), "species" [species of each set],
//         "text" (canonical export without nicknames, "" if nothing parsed), "problems" [validator messages,
//         empty = legal in <format> today]}
const readline = require('readline');
const {Dex, Teams, TeamValidator} = require(process.argv[2]);

const validator = TeamValidator.get(process.argv[3] || 'gen9ou');
const rl = readline.createInterface({input: process.stdin, terminal: false});
rl.on('line', line => {
	if (!line.trim()) return;
	const {id, text} = JSON.parse(line);
	let out;
	try {
		const team = Teams.import(text) || [];
		for (const set of team) {
			set.name = set.species;  // nicknames carry nothing; dedupe without
			// ids -> display names (generated teams are written with ids)
			const name = (table, x) => (x && table.get(x).exists ? table.get(x).name : x);
			set.species = name(Dex.species, set.species);
			set.name = set.species;
			set.item = name(Dex.items, set.item);
			set.ability = name(Dex.abilities, set.ability);
			set.moves = set.moves.map(m => name(Dex.moves, m));
			set.nature = name(Dex.natures, set.nature);
			if (set.teraType) set.teraType = name(Dex.types, set.teraType);
		}
		// export before validating: the validator may modify the sets
		const canonical = team.length ? Teams.export(team).trim() : '';
		const species = team.map(s => s.species);
		const problems = team.length ? (validator.validateTeam(team) || []) : ['no sets parsed'];
		out = {id, n: team.length, species, text: canonical, problems};
	} catch (e) {
		out = {id, n: 0, species: [], text: '', problems: [`error: ${e.message}`]};
	}
	process.stdout.write(JSON.stringify(out) + '\n');
});
