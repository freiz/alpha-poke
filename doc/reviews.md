# Game reviews

The search's second opinion on a game, decision by decision (`alpha_poke.coach`). It may help
newer players spot clear slips; it is not a verdict on strong players (see "How far to trust it").

## What it does

Every decision of the chosen player (turn starts, switches after a faint, pivot switches) is
rebuilt from that player's own view, the way the training data is: their team, what the opponent
has revealed so far, belief samples for the rest. Each decision is searched as the bot would
play it, several times over independent draws of everything hidden, giving per option:

- the estimated winning chance after it, with its error (the spread of the repeated searches);
- the search's share of thinking (visits);
- the gap to the search's own choice, shown as "≈" when it is within the error.

A decision is marked "the AI disagrees" when the loss is at least 3 points and beyond the error,
and either the search hardly considered the choice or the loss is at least 5 points; "the AI
doesn't like it" when the search hardly considered the choice but the loss is uncertain; a loss
under 3 points is always acceptable. The error multiple and the "hardly considered" share are
adjustable on the page, which states the rule in full. A scorecard sums up the game: how often the player chose the search's
first or second choice, the average winning chance lost, the number of marked decisions.

Each turn also shows what the search expected of the opponent (its options at the root, with the
player's chance after each: a guess, the opponent's sets unknown) and what the opponent did. When
the winning chance moves by 15 points or more by the next decision, the page says why, from
templates, no language model: the turn's luck from the log (a critical hit, a miss, a full
paralysis, a flinch, a thaw that did not come, a hit in confusion) and an opponent's choice that
left the player 5 points or more better or worse off than the one the search expected; with
neither, what the turn revealed changed the picture.

## Using it

```bash
uv run python scripts/review_server.py   # the app: http://127.0.0.1:8090 (--lan: the local network)
uv run python scripts/review_game.py <replay URL, id or file> --player <name> --open   # one game, no app
```

- **Input**: a Showdown replay link or id, or a saved replay file (.html / .json / log). Gen 9
  OU only.
- **Your team** (optional): a Showdown export or a PokéPaste link. With it your sets are exact;
  without it the parts the game did not show are guessed anew in each repeated search, and the
  error ranges grow.
- **Strength**: fast / standard / deep, or custom (searches × seconds × belief worlds); several
  searches run at once. The home page shows the number of decisions and the estimated time.
- **Review again**: on the review page, with a deeper setting or from the other player's view.
- **The list of reviews**: searchable, sortable, with both teams, the result and the scorecard;
  each review can be renamed and noted on (`data/coach/reviews.sqlite`).
- **A write-up** (`review_game.py --llm`): an OpenAI-compatible chat model (`.env`:
  `COACH_LLM_*`) writes a coach's summary from the numbers only; the moves it names are checked
  against the teams' learnsets.

The page shows Showdown's own replay player beside the review. Showdown's client (AGPL-3.0) is
fetched once into `data/coach/client/` and served unmodified for local viewing, never committed.
Windows / macOS builds of the app (no Python or Rust needed): `.github/workflows/desktop-app.yml`.

## How far to trust it

- The numbers are estimates: a few seconds of search per decision over sampled hidden sets.
- The search has blind spots: plans that pay off many turns later (it once gave a player who went
  on to win a Kingambit endgame 25%), reads of one particular opponent's habits, the opponent's
  speed.
- On held-out ladder games its first choice agreed with 1600+ players about as often as with
  1400–1600 players (51% vs 48%), and the average winning chance lost does not separate rating
  bands at all ([results.md](results.md), "Search agreement with players by rating band"). It is
  not a skill score.

A marked decision is a question worth a second look, not a proven mistake. The screenshot in the
README is a game between our bot and Foul Play, reviewed from Foul Play's side with its team
pasted: on turn 6 its Great Tusk (+2 Attack) switches out to Corviknight, the opposing Great Tusk
boosts again and knocks Corviknight out with Close Combat the next turn. Every option that stays
in is rated above the switch (Rapid Spin 37%, Bulk Up 33%, the switch 21%, each ± 1-2).
