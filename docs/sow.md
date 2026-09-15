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

1. Elastic Cloud only (free trial) — no self-hosted ES. (Originally
   Serverless; the shared deployment ended up being Cloud Hosted 9.5.3, which
   supports everything below.)
2. Explicit mappings for every index — no dynamic mapping.
3. Elastic Inference Service (EIS) for any LLM/embedding needs — no external
   API keys, no self-managed model deployment.
4. Must demonstrate: (a) aggregations, (b) ES|QL, (c) vector/semantic search,
   (d) an Agent Builder custom agent with tools.
5. Odds API key and Elastic API key live in `.env` (gitignored) — never
   committed.

## Deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Index mappings: `nba_team_stats`, `nba_games`, `nba_odds` | ✅ scaffolded — [mappings/](../mappings/) |
| 2 | Sample docs for all 3 indices (unblocks development pre-ingestion) | ✅ done — [mappings/sample_docs.md](../mappings/sample_docs.md) |
| 3 | Ingest script: NBA team/game stats (stats.nba.com via `nba_api`; balldontlie.io now requires a key) | ✅ live — [ingest/fetch_nba_games.py](../ingest/fetch_nba_games.py), [ingest/fetch_nba_stats.py](../ingest/fetch_nba_stats.py) |
| 4 | Ingest script: NBA odds (The Odds API) | ✅ live — [ingest/fetch_odds.py](../ingest/fetch_odds.py) |
| 5 | Win-probability formula (ES|QL) | 🚧 drafted — [esql/win_probability.esql](../esql/win_probability.esql) |
| 6 | Stats-vs-market comparison query | 🚧 drafted — [esql/matchup_comparison.esql](../esql/matchup_comparison.esql) |
| 7 | Vector/semantic search: `narrative` semantic_text field + search query | 🚧 drafted — [mappings/nba_team_stats.json](../mappings/nba_team_stats.json), [esql/team_narrative_search.esql](../esql/team_narrative_search.esql) |
| 8 | Agent Builder: 5 tools + 1 agent | 🚧 drafted — [agent_builder/setup.md](../agent_builder/setup.md) |
| 8b | Aggregations (ES\|QL `STATS`) | 🚧 drafted — [esql/league_aggregates.esql](../esql/league_aggregates.esql), `get_league_context` tool |
| 9 | Demo script | ✅ done — [docs/demo_script.md](demo_script.md) |
| 10 | Model explanation doc | ✅ done — [docs/model.md](model.md) |

## Acceptance criteria

- [x] All three indices exist in the Elastic deployment with the
      explicit mappings in `mappings/`, not dynamically inferred.
- [x] `nba_team_stats` and `nba_games` are populated from stats.nba.com
      (live data, not just the sample docs).
- [x] `nba_odds` is populated from The Odds API with de-vigged implied
      probabilities.
- [ ] The win-probability ES|QL query runs and returns a ranked list of
      teams.
- [ ] An ES|QL `STATS` aggregation runs (hard requirement 4a). Until
      `esql/league_aggregates.esql` was added, every rollup in the project
      happened in Python and nothing aggregated inside Elasticsearch —
      requirement 4a was silently unmet and not tracked anywhere.
- [ ] The agent can answer "is there a value mismatch in [team A] vs
      [team B]?" by chaining `get_stats_prediction` + `get_market_odds` and
      stating a clear delta.
- [ ] The agent can answer "which games have the biggest gap tonight?" via
      `find_value_mismatches`.
- [x] Every `nba_team_stats` doc has a `narrative` (semantic_text) value,
      embedded automatically by EIS at index time.
- [ ] The agent can answer a play-style question ("which teams are playing
      lockdown defense on a hot streak?") via `find_similar_teams`, returning
      teams matched by meaning, not exact keywords.
- [ ] Every agent response frames output as analysis, never as betting
      advice.
- [ ] Demo rehearsed end-to-end at least once before presenting.

## Non-goals (explicitly out of scope for tonight)

- No trained ML classifier / no sklearn.
- No real-money betting integration of any kind.
- No custom embedding model — semantic search uses the EIS default model
  via `semantic_text` only.

## Team split

See [docs/todo.md](todo.md) for the full task breakdown between Aaron and
Raymond, structured so neither person blocks the other.
