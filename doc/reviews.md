# Game reviews

A second opinion on a Pokémon Showdown Gen 9 OU singles game, decision by decision
(`alpha_poke.coach`). Two parts do the work:

- **The engine** (built in, nothing to set up): this project's own battle AI, the network with
  its search, as a chess engine. It rethinks every decision and gives the numbers: each option's
  winning chance, its first choice, the marked decisions.
- **The coach** (optional): a language model the player sets up, which reads the engine's
  analysis and writes about it: the player's style, the team, and answers to questions on any
  decision. Without it the review is complete; only those write-ups and the questions are
  missing.

The pages keep the two names apart ("the engine disagrees", "Ask the coach"); they used to say
"AI" for both. A review may help newer players spot clear slips; it is not a verdict on strong
players (see "How far to trust it").

## What it does: the engine

Every decision of the chosen player (turn starts, switches after a faint, pivot switches) is
rebuilt from that player's own view, the way the training data is: their team, what the opponent
has revealed so far, belief samples for the rest. Each decision is searched as the bot would
play it, several times over independent draws of everything hidden, giving per option:

- the estimated winning chance after it, with its error (the spread of the repeated searches);
- the search's share of thinking (visits);
- the gap to the search's own choice, shown as "≈" when it is within the error.

A decision is marked "the engine disagrees" when the loss is at least 3 points and beyond the
error, and either the search hardly considered the choice or the loss is at least 5 points; "the
engine doesn't like it" when the search hardly considered the choice but the loss is uncertain; a
loss under 3 points is always acceptable. Without the player's team, the engine's first choice can
be a move it only guessed the player has: if the player's choice is the best of the moves they
surely have, it reads "best of your known moves", not a mistake. The error multiple and the
"hardly considered" share are adjustable on the page, which states the rule in full. A scorecard
sums up the game: how often the player chose the search's first or second choice, the average
winning chance lost, the number of marked decisions.

Each turn also shows what the search expected of the opponent (its options at the root, with the
player's chance after each: a guess, the opponent's sets unknown) and what the opponent did. When
the winning chance moves by 15 points or more by the next decision, the page says why, from
templates, no language model: the turn's luck from the log (a critical hit, a miss, a full
paralysis, a flinch, a thaw that did not come, a hit in confusion) and an opponent's choice that
left the player 5 points or more better or worse off than the one the search expected, with the
line the search feared after it; with neither, what the turn revealed changed the picture.

Each turn also lists the search's main lines, as KataGo shows its variations: for the player's
two most considered options and the opponent's two likeliest replies to each, the most visited
choices of both sides for four steps (`alpha_search.ismcts(pv=...)`), played out by the engine
in every world of the decision -- each step's actives with their median HP and how often one
fainted. The search's tree does not branch on chance outcomes, so a line is its main
expectation, not a single game.

## Using it

```bash
uv run python scripts/review_server.py   # the app: http://127.0.0.1:8090 (--lan: the local network)
uv run python scripts/review_game.py <replay URL, id or file> --player <name> --open   # one game, no app
```

- **Input**: a Showdown replay link or id, or a saved replay file (.html / .json / log). Gen 9
  OU singles only (`replays.REVIEWABLE`, the one place to widen later): the format and the
  battle type are read from the log's own `|tier|` / `|gametype|` lines, not the file's name, and
  a game that is not one is refused with the reason (a doubles battle, another format or
  generation, a log without its format).
- **Your team** (optional): a Showdown export or a PokéPaste link. With it your sets are exact;
  without it the parts the game did not show are guessed anew in each repeated search, and the
  error ranges grow.
- **Strength**: fast / standard / deep, or custom (searches × seconds × belief worlds); several
  searches run at once. The home page shows the number of decisions and the estimated time.
- **Review again**: on the review page, with a deeper setting or from the other player's view.
- **The list of reviews**: searchable, sortable, with both teams, the result and the scorecard;
  each review can be renamed and noted on (`data/coach/reviews.sqlite`).
- **The team against the metagame** (`coach.meta`, no language model; shown at once when the team
  analysis opens): from a snapshot shipped with the app (`scripts/knowledge.py`: fetch, build,
  validate, promote -- doc/team_design.md) -- the team's archetype (`teams.archetypes`: its style
  by a classifier fit on the forum's titled teams, leave-one-out 75% against 52% for hand rules;
  its features by rules; the team's expected score by the style it meets, and the answers to its
  style where the matchup model and the games agree), the matchup model's
  expected score against the recent metagame and over its hardest fifth (species, rating-adjusted,
  with a teammate term: held-out log loss 0.6896 ratings only, 0.6798 with species, 0.6778 with
  teammates), the threats it fears, each member's rank, counters and usual teammates, the team's
  pairs on the ladder and in the model, the model's swap leads, similar forum / ladder teams, and
  a set-by-set threat check (the damage model: which of the team checks or revenge-kills each
  popular threat's main builds, which it KOs; the sets exact when pasted). Nothing is fetched on
  the player's computer. A snapshot ships only when its checks pass (`teams.knowledge_checks`:
  OU legality by the local Showdown's rules, freshness, threat coverage, the model's held-out
  loss, the archetypes against the forum's titles, the move since the last snapshot, and the
  damage model against poke-engine); a species banned since is never suggested.
- **The coach** (`coach.llm`, optional): see below.

The page shows Showdown's own replay player beside the review. Showdown's client (AGPL-3.0) is
fetched once into `data/coach/client/` and served unmodified for local viewing, never committed.
Windows / macOS builds of the app (no Python or Rust needed): `.github/workflows/desktop-app.yml`.

## The coach (optional)

A language model's write-ups on the review page, from the review's facts:

- **Style** (操作风格评价): how the game was played, its turning points -- the largest swings of the
  winning chance with their causes (the player's choice, the opponent's mistake or good play, or
  luck from the log; both sides' biggest mistakes, and a win the opponent or luck handed over said
  so) --, what went well, the habits to work on, what to practise.
- **Team** (队伍分析): this game's matchup first -- set by set both ways (who checks or
  revenge-kills each opponent, who KOs whom in one hit), the speed order, the first turn's
  chance --, then the weaknesses it exposed and the directions to try, within the team's common
  sets and the metagame facts above.
- **Ask the coach** (问教练): a side panel beside any decision, a conversation with follow-ups
  (the whole conversation sent with each); each decision's button shows how many questions it
  has; the conversation is kept with the review and can be cleared; `#ask=<decision>` opens one.
  Only that decision's facts, about 5,000 tokens.

The write-ups are in the page's language and kept with their review; "↻ Write it again" clears
the old text while the new one is written. The coach speaks as a character of the main games
(a character card for the voice, the opening and the closing line only -- Cynthia by default,
Nemona, Iris, Marnie, Geeta, Penny, or none); a write-up ends with her encouragement and a
signature, answers in a conversation do not. The rules and the data come first:

- this game's facts (moves, items, sets, events, numbers) only from the data, Showdown's Chinese
  names for everything; every move it names, in either language, is checked against the teams'
  learnsets and the moves used;
- the engine's analysis is a model's and not perfect (a few turns ahead, the opponent's hidden
  sets guessed, chances with errors): the coach takes it as the main reference and judges too,
  from general battle knowledge (matchups, plans, win conditions, tempo) -- a different view said
  as its own, with the reason, apart from the engine's numbers; the reader reminded once, not in
  every paragraph.

**Setting it up** (the home page, from this computer only):

- The address of any OpenAI-compatible API and its key; the model is then chosen from the
  service's own list (its `GET /models`: Ollama, OpenAI, OpenRouter, DeepSeek and the like serve
  it), typed by hand only when the list cannot be had. The saved key is reused for the saved
  address only.
- A model on this computer (Ollama: `http://localhost:11434/v1`) needs no key. Raise Ollama's
  context to 32k or more (`OLLAMA_CONTEXT_LENGTH=32768`): a game's facts are about 27,000 tokens
  for 40 turns, and a shorter context cuts them silently.
- Use a strong model, above 45 on the [Artificial Analysis Intelligence
  Index](https://artificialanalysis.ai/#intelligence) v5.0: a smarter model catches more of the
  details and makes up less; a weaker one gets moves and turns wrong or calls luck a mistake.
- The key stays in the data directory (`coach/llm.json`, this user's only) and is never sent
  back to a page. With the coach on, the review's facts go to the model's address (`coach.packet`:
  both teams with their types, base stats, matchups and moves seen, the ladder's common sets, the
  log, every decision's numbers, the metagame facts); the engine itself sends nothing anywhere.

`review_game.py --llm` writes the older one-shot summary (`.env`: `COACH_LLM_*`).

## How far to trust it

- The engine's numbers are estimates: a few seconds of search per decision over sampled hidden
  sets.
- The search has blind spots: plans that pay off many turns later (it once gave a player who went
  on to win a Kingambit endgame 25%), reads of one particular opponent's habits, the opponent's
  speed.
- On held-out ladder games its first choice agreed with 1600+ players about as often as with
  1400–1600 players (51% vs 48%), and the average winning chance lost does not separate rating
  bands at all ([results.md](results.md), "Search agreement with players by rating band"). It is
  not a skill score.

- The coach's words are a language model's: checked for invented moves, told the engine's limits,
  but still able to be wrong; a stronger model is wrong less often.

A marked decision is a question worth a second look, not a proven mistake. The screenshot in the
README is a game between our bot and Foul Play, reviewed from Foul Play's side with its team
pasted: on turn 6 its Great Tusk (+2 Attack) switches out to Corviknight, the opposing Great Tusk
boosts again and knocks Corviknight out with Close Combat the next turn. Every option that stays
in is rated above the switch (Rapid Spin 37%, Bulk Up 33%, the switch 21%, each ± 1-2).
