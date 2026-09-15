# Agent Builder Setup

Two paths, same result:

- **Fast path — Dev Tools Console:** paste the four blocks below (three tools
  + one agent) into Kibana's Dev Tools Console, run each, done.
- **Manual walkthrough:** build the same tools field-by-field in the Agent
  Builder UI (**Kibana → Agents → Tools → New tool**) if you want to
  understand/tweak each piece.

Requires `nba_team_stats` and `nba_odds` to have data in them (see
[../mappings/sample_docs.md](../mappings/sample_docs.md) if ingestion isn't
done yet — the tools work identically against sample or live data).

---

## Tool 1 — `get_market_odds`

Returns odds + implied probability for a given game/team.

```json
PUT kbn:/api/agent_builder/tools/get_market_odds
{
  "type": "esql",
  "description": "Get the current sportsbook odds and implied win probability for a given NBA team and/or game.",
  "configuration": {
    "query": "FROM nba_odds | WHERE team == ?team OR game_id == ?game_id | KEEP game_id, date, home_team, away_team, bookmaker, team, odds_decimal, implied_probability | SORT date DESC",
    "params": {
      "team": { "type": "keyword", "description": "Team name, e.g. 'Boston Celtics'. Optional if game_id is given." },
      "game_id": { "type": "keyword", "description": "Game id, e.g. '2026-09-20-BOS-NYK'. Optional if team is given." }
    }
  }
}
```

> Watch the `OR` here. Some Agent Builder versions require every declared
> `?param` to be supplied on each call, so "optional if the other is given"
> may not hold in practice — a call with only `team` can error on the missing
> `game_id` rather than ignoring it. If that happens, have the agent pass an
> empty string for the unused one, or split this into two single-param tools
> (`get_odds_by_team`, `get_odds_by_game`). Worth testing early; it's a
> two-minute fix but an ugly thing to discover mid-demo.

## Tool 2 — `get_stats_prediction`

Returns the stats-based win probability for a given team, using the formula
documented in [../docs/model.md](../docs/model.md).

```json
PUT kbn:/api/agent_builder/tools/get_stats_prediction
{
  "type": "esql",
  "description": "Get the stats-based win probability estimate for a given NBA team, derived from net rating and recent form (not a betting line).",
  "configuration": {
    "query": "FROM nba_team_stats | WHERE team == ?team | EVAL last_10_games = last_10_wins + last_10_losses | EVAL last_10_win_pct = CASE(last_10_games == 0, 0.5, TO_DOUBLE(last_10_wins) / TO_DOUBLE(last_10_games)) | EVAL raw_score = ROUND((net_rating * 0.5) + (last_10_win_pct * 30), 2) | KEEP team, net_rating, last_10_wins, last_10_losses, last_10_win_pct, raw_score",
    "params": {
      "team": { "type": "keyword", "description": "Team name, e.g. 'Boston Celtics'." }
    }
  }
}
```

> Two things to know about this tool's output:
>
> 1. **It's a neutral-court score.** This tool takes a team, not a game, so it
>    has no way to know who's at home and doesn't apply the +5 home-court
>    bonus. The agent instructions tell it to add the +5 itself when it knows
>    the venue. `find_value_mismatches` starts from the odds index, so it
>    *does* have `home_team` and applies the bonus in ES|QL.
> 2. **`raw_score` is not a probability.** Converting a pair of scores is
>    `P(team_a) = 1 / (1 + exp(-(score_a - score_b) / 10))` — the two-class
>    softmax with the scale divisor from
>    [../docs/model.md](../docs/model.md). Do not use the unscaled
>    `exp(a)/(exp(a)+exp(b))`: on real inputs it returns 100.0% and makes
>    every game look like a massive mismatch. Keeping this math in the LLM's
>    reasoning step rather than ES|QL is deliberate — it's what makes the
>    thinking trace demo-able ("here's the formula, here's the conversion").

## Tool 3 — `find_value_mismatches`

Returns all teams with both a stats prediction and market odds, so the agent
can compute deltas across every game at once.

```json
PUT kbn:/api/agent_builder/tools/find_value_mismatches
{
  "type": "esql",
  "description": "Get stats-based raw scores and market implied probabilities for every team with upcoming odds, to find games where the stats model and the market disagree.",
  "configuration": {
    "query": "FROM nba_odds | WHERE market == \"h2h\" | LOOKUP JOIN nba_team_stats ON team | WHERE net_rating IS NOT NULL | EVAL last_10_games = last_10_wins + last_10_losses | EVAL last_10_win_pct = CASE(last_10_games == 0, 0.5, TO_DOUBLE(last_10_wins) / TO_DOUBLE(last_10_games)) | EVAL is_home = team == home_team | EVAL raw_score = ROUND((net_rating * 0.5) + (last_10_win_pct * 30) + CASE(is_home, 5.0, 0.0), 2) | KEEP game_id, date, home_team, away_team, team, is_home, bookmaker, implied_probability, net_rating, last_10_win_pct, raw_score | SORT date ASC, game_id ASC"
  }
}
```

### If `LOOKUP JOIN` fails

`LOOKUP JOIN` only targets an index created in **lookup mode**, and this used
to be the riskiest thing in the project — the original
`mappings/nba_team_stats.json` created an ordinary index, so the join failed
outright.

**This is now handled by ingest.** `ingest/indices.py` creates
`nba_team_stats` with `index.mode: lookup` as a versioned index behind an
alias, and Aaron has confirmed the join works through that alias against live
data with zero unmatched odds rows. So the tool above should work as
committed, and there is no mirror index to build or keep in sync.

Two ways it can still bite you:

- **A stale concrete index.** If `nba_team_stats` exists as a real index
  rather than an alias — typically left behind by an old dynamically-mapped
  ingest run — `ensure_index()` refuses to run and tells you to
  `DELETE nba_team_stats` and re-run. Do that rather than working around it;
  a dynamically-mapped index has quietly lost both lookup mode and the
  `semantic_text` field.
- **Unmatched team names.** The join is on exact team name. `ingest/teams.py`
  canonicalizes stats.nba.com's "LA Clippers" to "Los Angeles Clippers" to
  match the Odds API. If a team silently vanishes from cross-game results,
  check for a name that didn't canonicalize — the `WHERE net_rating IS NOT
  NULL` guard in the tool drops those rows rather than scoring them with null
  stats, so they disappear quietly rather than producing a wrong number.

**Last-resort fallback.** If the join is unavailable on your tier despite the
above, register this tool and drop `find_value_mismatches` from the agent:

```json
PUT kbn:/api/agent_builder/tools/get_all_stats_scores
{
  "type": "esql",
  "description": "Get the neutral-court stats raw_score for every NBA team at once, for cross-game comparison when a join is unavailable.",
  "configuration": {
    "query": "FROM nba_team_stats | EVAL last_10_games = last_10_wins + last_10_losses | EVAL last_10_win_pct = CASE(last_10_games == 0, 0.5, TO_DOUBLE(last_10_wins) / TO_DOUBLE(last_10_games)) | EVAL raw_score_neutral = ROUND((net_rating * 0.5) + (last_10_win_pct * 30), 2) | KEEP team, team_abbreviation, net_rating, last_10_win_pct, raw_score_neutral | SORT raw_score_neutral DESC"
  }
}
```

The agent then calls it once alongside `get_market_odds` and joins by team
name in its reasoning. Costs: neutral-court scores, so the agent must add the
+5 itself, and a longer trace.

## Tool 4 — `find_similar_teams`

**This is the vector/semantic search tool.** Finds teams by play-style/form
description using semantic search over the `narrative` field (a
`semantic_text` field embedded by ELSER on the Elastic Inference Service —
see [../mappings/nba_team_stats.json](../mappings/nba_team_stats.json)), not
keyword matching.

```json
PUT kbn:/api/agent_builder/tools/find_similar_teams
{
  "type": "esql",
  "description": "Semantic search for NBA teams matching a natural-language play-style or form description, e.g. 'lockdown defense on a hot streak' or 'struggling on the road with cold shooting'. Use this when the user describes a vibe/style rather than naming a specific stat.",
  "configuration": {
    "query": "FROM nba_team_stats METADATA _score | WHERE MATCH(narrative, ?description) | KEEP team, narrative, _score, net_rating, last_10_wins, last_10_losses | SORT _score DESC | LIMIT 10",
    "params": {
      "description": { "type": "keyword", "description": "Natural-language description of the play style or form to search for." }
    }
  }
}
```

> **Sort by `_score`, not by a stat.** This query originally ended with
> `SORT net_rating DESC`, which threw away the semantic ranking — the tool
> would return teams ordered by how *good* they are rather than how well they
> match the description, which defeats the point of the tool. Worse, it made
> the natural test ("search for a hot defensive team, check Boston ranks
> above New York") impossible to fail, since Boston sorts first on
> `net_rating` regardless. `METADATA _score` + `SORT _score DESC` is what
> makes this an actual relevance query.
>
> The agent instructions tell it to preserve this ordering and not re-sort.
> Worth checking in the thinking trace: a team can match "scrappy defensive
> team having a rough month" well while being near the bottom of the league,
> and that's the correct answer, not a bug.

> If `MATCH()` on a `semantic_text` field isn't supported on your Elastic
> version's ES|QL yet, fall back to a `query` (Query DSL) type tool using the
> `semantic` query documented in
> [../esql/team_narrative_search.esql](../esql/team_narrative_search.esql).

## Agent — `nba_value_finder`

```json
PUT kbn:/api/agent_builder/agents/nba_value_finder
{
  "name": "NationalBettingAssociation Analyst",
  "description": "Compares stats-based NBA win probability estimates against live sportsbook odds to find value gaps.",
  "tools": ["get_market_odds", "get_stats_prediction", "find_value_mismatches", "find_similar_teams"],
  "instructions": "You are the NationalBettingAssociation Analyst. You compare a transparent, stats-based win-probability estimate against live sportsbook odds for NBA games, and explain where they diverge.\n\nYour job is ANALYSIS AND INSIGHT ONLY. Never phrase output as betting advice, a recommendation to place a wager, or a guarantee, and never tell a user what to bet or how much, even if asked directly. Always frame findings as 'the stats model estimates X% vs the market's Y%' and let the user draw their own conclusions. If a user asks what they should bet on, explain what the model sees and decline the recommendation.\n\nTHE MATH. Follow these three steps exactly. Do not improvise a shortcut; show each step in your reasoning so the user can check it.\n\nStep 1 - raw_score. The tools return raw_score already computed as (net_rating * 0.5) + (last_10_win_pct * 30) + home_court_bonus. The home_court_bonus is +5 for the home team and 0 for the away team. find_value_mismatches already includes it (check the is_home field). get_stats_prediction does NOT - it takes a team, not a game, so if you used get_stats_prediction and you know which team is at home, add 5 to that team's raw_score yourself and say that you did.\n\nStep 2 - convert the pair of scores to a probability using a logistic with a scale divisor of 10:\n  P(team_a) = 1 / (1 + exp(-(raw_score_a - raw_score_b) / 10))\n  P(team_b) = 1 - P(team_a)\nThe divisor of 10 is REQUIRED. Do not use the unscaled softmax exp(a)/(exp(a)+exp(b)): typical score gaps are 10-20 points and the unscaled form returns 100%, which is wrong. If you ever compute a probability above 97% or below 3%, you have almost certainly dropped the divisor - recheck before answering.\n\nStep 3 - de-vig the market before comparing. Add the two teams' implied_probability values for the game. The total will usually be slightly above 1.0 (the bookmaker's margin). Divide each team's implied_probability by that total so the pair sums to 1.0. Only then compute the delta. Normalizing an already-normalized pair changes nothing, so always do it.\n\nThen: delta = model_probability - de-vigged_market_probability, stated in percentage points. The two teams' deltas must be exact mirrors of each other (+N and -N). If they are not, you skipped step 3 - go back and redo it.\n\nWORKED EXAMPLE, for calibration. Boston (home, net_rating 12.2, last 10: 8-2) vs New York (away, net_rating 2.3, last 10: 6-4). Boston raw_score = 6.1 + 24 + 5 = 35.1. New York = 1.15 + 18 + 0 = 19.15. Gap 15.95, divided by 10 is 1.595, so P(Boston) = 83.1%. Market implied 0.6095 and 0.3905 already sum to 1.0, so de-vigging leaves them at 61.0% and 39.0% - run the step anyway, because live bookmaker rows may not be normalized. Delta: Boston +22.2pp, New York -22.2pp. Flag it, since it clears the 8pp threshold.\n\nWHEN ASKED ABOUT A SPECIFIC MATCHUP: call get_stats_prediction for both teams and get_market_odds for the game, then run the three steps. State the delta, then explain in plain language WHY the model landed where it did - point at the actual net_rating and recent-form numbers that drove it.\n\nWHEN ASKED TO FIND MISMATCHES ACROSS GAMES: call find_value_mismatches, group the rows by game_id, run the three steps per game, and rank by absolute delta. Report the top 3-5. Skip any game that came back with only one team's row - you cannot compute a pairwise probability from one score, so say the game was skipped for missing data rather than guessing.\n\nWHEN THE USER DESCRIBES A PLAY STYLE OR VIBE rather than naming a team or a stat (e.g. 'which teams are playing lockdown defense right now', 'find me a cold-shooting road team'): call find_similar_teams with their description. That tool searches team narratives semantically, so pass the user's phrasing through roughly as-is rather than translating it into stat names. Its results are ranked by how well the narrative matches the description, so preserve the order it returns and do not re-sort by net_rating - a team can match the description well while not being the best team. If the user then asks how good one of those teams actually is, or about a specific game, switch to the numeric tools above.\n\nDATA CAVEATS. A team with no last-10 record has last_10_win_pct defaulted to 0.5; if that team appears in your answer, say its recent form was unavailable. If a team has no stats row at all, say so instead of scoring it.\n\nHOW IT WORKS, if asked: a transparent weighted heuristic over net rating, last-10 form, and home court, with hand-chosen weights that were not fit to historical data. It is not a trained machine learning model, it has no injury or lineup data, and the scale divisor of 10 is a judgment call. Be straightforward about all of that."
}
```

---

## Demo prompts

```
Is there a value mismatch in tonight's Celtics vs Knicks odds?
```
```
Which games tonight have the biggest gap between the market and the stats model?
```
```
Break down the win probability for the Celtics' next game and explain the formula.
```
```
Which teams are playing lockdown defense and on a hot streak right now?
```

Watch the **thinking trace** — the agent should call 2-3 tools in sequence
before answering. That trace is the actual demo material for judges.
