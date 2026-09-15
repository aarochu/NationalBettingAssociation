# Scope of Work — NationalBettingAssociation

Built for the Elastic Rutgers Hack Night. ~3-4 hour build window.

## Project

A stats-vs-market "value gap" finder for NBA games: compute a transparent,
stats-based win-probability estimate from team performance data, compare it
against live sportsbook odds, and surface where the two disagree — through an
Elasticsearch-backed Agent Builder agent.

This is **Path A** — a transparent, explainable heuristic scoring formula, not
a trained ML classifier.

## Hard requirements

1. Elastic Cloud Serverless only (free trial) — no self-hosted ES.
2. Explicit mappings for every index — no dynamic mapping.
3. Elastic Inference Service (EIS) for any LLM/embedding needs — no external
   API keys, no self-managed model deployment.
4. Must demonstrate: (a) aggregations, (b) ES|QL, (c) an Agent Builder custom
   agent with tools.
5. Odds API key and Elastic API key live in `.env` (gitignored) — never
   committed.

## Deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Index mappings: `nba_team_stats`, `nba_games`, `nba_odds` | ✅ scaffolded — [mappings/](../mappings/) |
| 2 | Sample docs for all 3 indices (unblocks development pre-ingestion) | ✅ done — [mappings/sample_docs.md](../mappings/sample_docs.md) |
| 3 | Ingest script: NBA team/game stats (balldontlie.io) | 🚧 stubbed — [ingest/fetch_nba_stats.py](../ingest/fetch_nba_stats.py), [ingest/fetch_nba_games.py](../ingest/fetch_nba_games.py) |
| 4 | Ingest script: NBA odds (The Odds API) | 🚧 stubbed — [ingest/fetch_odds.py](../ingest/fetch_odds.py) |
| 5 | Win-probability formula (ES|QL) | 🚧 drafted — [esql/win_probability.esql](../esql/win_probability.esql) |
| 6 | Stats-vs-market comparison query | 🚧 drafted — [esql/matchup_comparison.esql](../esql/matchup_comparison.esql) |
| 7 | Agent Builder: 3 tools + 1 agent | 🚧 drafted — [agent_builder/setup.md](../agent_builder/setup.md) |
| 8 | Demo script | ✅ done — [docs/demo_script.md](demo_script.md) |
| 9 | Model explanation doc | ✅ done — [docs/model.md](model.md) |

## Acceptance criteria

- [ ] All three indices exist in the Elastic Serverless project with the
      explicit mappings in `mappings/`, not dynamically inferred.
- [ ] `nba_team_stats` and `nba_games` are populated from balldontlie.io
      (live data, not just the sample docs).
- [ ] `nba_odds` is populated from The Odds API with de-vigged implied
      probabilities.
- [ ] The win-probability ES|QL query runs and returns a ranked list of
      teams.
- [ ] The agent can answer "is there a value mismatch in [team A] vs
      [team B]?" by chaining `get_stats_prediction` + `get_market_odds` and
      stating a clear delta.
- [ ] The agent can answer "which games have the biggest gap tonight?" via
      `find_value_mismatches`.
- [ ] Every agent response frames output as analysis, never as betting
      advice.
- [ ] Demo rehearsed end-to-end at least once before presenting.

## Non-goals (explicitly out of scope for tonight)

- No trained ML classifier / no sklearn.
- No real-money betting integration of any kind.
- No custom embedding model — EIS defaults only, if semantic search over
  news/recaps is added as a stretch goal.

## Team split

See [docs/todo.md](todo.md) for the full task breakdown between Aaron and
Raymond, structured so neither person blocks the other.
