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

**Know the right answer before you ask.** On sample data this should come back
as roughly **Boston 83%, market 61%, delta +22pp**. Run
`python3 scripts/reference_model.py` right before you go on to confirm.

Two failure modes to catch in the moment:
- **Boston at ~100%** — the agent dropped the `/10` scale divisor. Don't
  argue with it on stage; move to Beat 4 and fix the instructions after.
- **Deltas that aren't mirrors** (e.g. +22 and −19) — it skipped the de-vig
  step. Minor enough to talk over if you notice it.

## Beat 3.5 — vector search (15s)

Ask:

```
Which teams are playing lockdown defense and on a hot streak right now?
```

> "That's semantic search — each team has a narrative field embedded by EIS,
> so it matches on meaning. None of those words have to appear in the data."

**This prompt only works on sample data.** The hand-written sample narratives
mention defense and shooting; `build_narrative()` in the ingest script never
produces either word — its vocabulary is limited to overall quality, last-10
form, and home/away. So on live data "lockdown defense" has nothing to match
and the result degrades to roughly a quality ranking, which looks like the
tool working while proving nothing.

Once live data lands, either use a prompt inside the template's actual
vocabulary:

```
Which teams are rolling right now and tough to beat at home?
```

or get `build_narrative()` widened first (flagged for Aaron in the todo). The
first option is the safe demo; the second is the better demo.

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
> Elastic Cloud with zero external API keys for the AI side thanks to
> EIS."

## If something breaks live

Have `mappings/sample_docs.md` data still indexed as a fallback — the demo
prompts work identically against sample data, so a live-API hiccup doesn't
kill the demo.

If Beat 4 errors, `find_value_mismatches` is the likely culprit —
`LOOKUP JOIN` needs a lookup-mode index. Fall back to asking about a second
named matchup instead, which only uses the two single-team tools. The fix and
the no-join fallback tool are in
[../agent_builder/setup.md](../agent_builder/setup.md).

One silent failure worth guarding against: if you built
`nba_team_stats_lookup` and Aaron's live data landed after that, the mirror is
stale and you'll be scoring live odds against sample stats. Re-run the
`_reindex` at the merge point.
