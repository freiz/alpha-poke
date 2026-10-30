"""Game reviews for people (2026-10-29): the search's judgement of a player's decisions in a
replay, the facts around them, and an optional language-model write-up.

  replays   a replay from a file (our saved .html, a .json / .log) or a Showdown replay id / URL
  review    each decision of one player searched from that player's view: the options' winning
            chances, the chosen one's, the loss against the search's choice; the turn's events
  narrate   the review as a coach's report by an OpenAI-compatible model (.env COACH_LLM_*),
            told to use only the review's numbers and facts

The search plays the game well but cannot explain it: the numbers say *which* decisions cost the
most, the facts (resisted or blocked moves, boosts, hazards, tera) say what happened; the
language model only puts them into words. scripts/review_game.py runs it.
"""
