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

## Tool 2 — `get_stats_prediction`

Returns the stats-based win probability for a given team, using the formula
documented in [../docs/model.md](../docs/model.md).

```json
PUT kbn:/api/agent_builder/tools/get_stats_prediction
{
  "type": "esql",
  "description": "Get the stats-based win probability estimate for a given NBA team, derived from net rating and recent form (not a betting line).",
  "configuration": {
    "query": "FROM nba_team_stats | WHERE team == ?team | EVAL last_10_win_pct = TO_DOUBLE(last_10_wins) / (TO_DOUBLE(last_10_wins) + TO_DOUBLE(last_10_losses)) | EVAL raw_score = (net_rating * 0.5) + (last_10_win_pct * 30) | KEEP team, net_rating, last_10_win_pct, raw_score",
    "params": {
      "team": { "type": "keyword", "description": "Team name, e.g. 'Boston Celtics'." }
    }
  }
}
```

> `raw_score` is not yet a 0-100% probability. The agent's instructions (below)
> tell it how to convert two teams' `raw_score` values into a probability via
> a softmax: `P(team_a) = exp(score_a) / (exp(score_a) + exp(score_b))`. This
> keeps the actual math out of ES|QL (which has no exp/softmax builtin) and
> in the LLM's reasoning step, which is transparent and explainable in the
> demo ("here's the formula, here's the conversion").

## Tool 3 — `find_value_mismatches`

Returns all teams with both a stats prediction and market odds, so the agent
can compute deltas across every game at once.

```json
PUT kbn:/api/agent_builder/tools/find_value_mismatches
{
  "type": "esql",
  "description": "Get stats-based raw scores and market implied probabilities for every team with upcoming odds, to find games where the stats model and the market disagree.",
  "configuration": {
    "query": "FROM nba_odds | LOOKUP JOIN nba_team_stats ON team | EVAL last_10_win_pct = TO_DOUBLE(last_10_wins) / (TO_DOUBLE(last_10_wins) + TO_DOUBLE(last_10_losses)) | EVAL raw_score = (net_rating * 0.5) + (last_10_win_pct * 30) | KEEP game_id, date, home_team, away_team, team, bookmaker, implied_probability, raw_score | SORT date"
  }
}
```

> If `LOOKUP JOIN` isn't available on your Elastic version/tier, fall back to
> two separate tool calls (`get_market_odds` + `get_stats_prediction` per
> team) and let the agent's instructions do the join in its reasoning step
> instead. Test this query first — it's the one most likely to need a
> fallback.

## Tool 4 — `find_similar_teams`

**This is the vector/semantic search tool.** Finds teams by play-style/form
description using semantic search over the `narrative` field (a
`semantic_text` field, auto-embedded by EIS — see
[../mappings/nba_team_stats.json](../mappings/nba_team_stats.json)), not
keyword matching.

```json
PUT kbn:/api/agent_builder/tools/find_similar_teams
{
  "type": "esql",
  "description": "Semantic search for NBA teams matching a natural-language play-style or form description, e.g. 'lockdown defense on a hot streak' or 'struggling on the road with cold shooting'. Use this when the user describes a vibe/style rather than naming a specific stat.",
  "configuration": {
    "query": "FROM nba_team_stats | WHERE MATCH(narrative, ?description) | KEEP team, narrative, net_rating, last_10_wins, last_10_losses | SORT net_rating DESC",
    "params": {
      "description": { "type": "keyword", "description": "Natural-language description of the play style or form to search for." }
    }
  }
}
```

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
  "instructions": "You are the NationalBettingAssociation Analyst. You compare a transparent, stats-based win-probability estimate against live sportsbook odds for NBA games, and explain where they diverge.\n\nYour job is ANALYSIS AND INSIGHT ONLY. Never phrase output as betting advice, a recommendation to place a wager, or a guarantee. Always frame findings as 'the stats model estimates X% vs the market's Y%' and let the user draw their own conclusions.\n\nWhen asked about a specific matchup:\n1. Call get_stats_prediction for both teams to get their raw_score.\n2. Convert raw_score to a probability using softmax: P(team_a) = exp(score_a) / (exp(score_a) + exp(score_b)).\n3. Call get_market_odds for the same game to get the market's implied_probability (already de-vigged).\n4. Compare the two probabilities and state the delta in percentage points.\n5. Explain WHY the stats model landed where it did (net rating, recent form) in plain language.\n\nWhen asked to find mismatches across all games, call find_value_mismatches, compute the softmax probability per game, and rank by absolute delta vs. the market's implied_probability. Report the top 3-5.\n\nWhen the user describes a play style, vibe, or form rather than naming a specific team or stat (e.g. 'which teams are playing lockdown defense right now' or 'find me a team like a cold-shooting road team'), call find_similar_teams with that description instead of trying to match it to a specific field.\n\nAlways disclose that the stats model is a simple weighted heuristic (net rating + recent form + home court), not a trained machine learning model, if asked how it works."
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
