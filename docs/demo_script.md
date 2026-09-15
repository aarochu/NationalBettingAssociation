# Demo script (~90 seconds)

**Goal:** show Elasticsearch doing real work (mappings, ES|QL, Agent Builder
tool chaining), not just a chat window.

## Beat 1 — the setup (15s)

> "We built NationalBettingAssociation — it compares a transparent,
> stats-based win-probability model against live sportsbook odds for NBA
> games, and flags where they disagree. Everything's in Elasticsearch:
> explicit mappings, ES|QL for the formula, and an Agent Builder agent that
> chains it all together."

## Beat 2 — show the queries (20s)

Flash the Dev Tools console:
- The `nba_team_stats` mapping (explicit types, not dynamic).
- `esql/win_probability.esql` running live, returning a ranked list of
  teams by raw score.

> "This is our win-probability formula — net rating plus recent form plus a
> home-court bump. It's a documented heuristic, not a black box."

## Beat 3 — the agent (40s)

Switch to Kibana → Agents, ask live:

```
Is there a value mismatch in tonight's Celtics vs Knicks odds?
```

Let the **thinking trace** show: `get_stats_prediction` called for both
teams → `get_market_odds` called → the agent computing the delta and
explaining it in plain language.

> "Watch it call our custom tools in sequence — pulling the stats prediction,
> pulling the market odds, then reasoning over both to explain the gap."

## Beat 3.5 — vector search (15s)

Ask:

```
Which teams are playing lockdown defense and on a hot streak right now?
```

> "That's semantic search — each team has a narrative field embedded by EIS,
> so it matches on meaning. None of those words have to appear in the data."

## Beat 4 — the payoff (15s)

Ask the follow-up:

```
Which games tonight have the biggest gap between the market and the stats model?
```

> "And it can scan every game at once to rank the biggest mismatches — this
> is pure analysis, not betting advice, but it's the same reasoning a
> sharp bettor does by hand, just automated over live Elasticsearch data."

## Closing line

> "The Kaggle-style datasets in the World Cup starter were simulated — ours
> is real, live NBA data and real, live sportsbook odds, running entirely on
> Elastic Serverless with zero external API keys for the AI side thanks to
> EIS."

## If something breaks live

Have `mappings/sample_docs.md` data still indexed as a fallback — the demo
prompts work identically against sample data, so a live-API hiccup doesn't
kill the demo.
