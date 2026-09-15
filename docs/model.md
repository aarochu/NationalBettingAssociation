# The stats model, explained

This is a **transparent weighted heuristic**, not a trained machine learning
model. Every number that goes into it is a real team stat, and every weight
is a design choice we can explain in the pitch. That's deliberate — Path A
was chosen over training an actual classifier because it fits the timebox and
because "here's exactly why the model thinks this" is a much better demo
moment than a black box.

## Inputs (per team, from `nba_team_stats`)

| Field | What it captures |
|---|---|
| `net_rating` | Points scored minus points allowed per 100 possessions (or a simplified per-game version) — the single best proxy for "how good is this team right now." |
| `last_10_wins` / `last_10_losses` | Recent form — weights recency over full-season record, since injuries/trades/momentum matter. |
| `home_win_pct` / `away_win_pct` | Home-court advantage, applied as a flat bonus rather than its own weighted term for simplicity. |

## Formula

```
last_10_win_pct = last_10_wins / (last_10_wins + last_10_losses)

raw_score = (net_rating * 0.5)
          + (last_10_win_pct * 30)
          + (home_court_bonus)   // +5 if this team is playing at home, else 0
```

The weights (`0.5`, `30`, `5`) are a starting point tuned by feel, not fit to
historical data — call this out explicitly in the pitch. If there's time,
a stretch goal is backtesting these weights against last season's actual
results and adjusting them, but that's optional.

## Converting two teams' scores into a probability

ES|QL doesn't have a built-in `exp()`/softmax function, so the final
probability conversion happens in the Agent Builder agent's reasoning step
(see the agent's `instructions` in [agent_builder/setup.md](../agent_builder/setup.md)):

```
P(team_a wins) = exp(raw_score_a) / (exp(raw_score_a) + exp(raw_score_b))
P(team_b wins) = 1 - P(team_a wins)
```

This is a standard softmax over two scores — it guarantees both
probabilities sum to 1.0 and rewards a larger score gap with a more lopsided
probability, without needing an arbitrary scale.

## Comparing against the market

The market's "implied probability" comes from converting sportsbook decimal
odds (`1 / odds_decimal`) and then **removing the vig** (bookmaker margin) by
normalizing both teams' implied probabilities to sum to 1.0 — see
`devig()` in [ingest/fetch_odds.py](../ingest/fetch_odds.py). Without this
step, both teams' raw implied probabilities would sum to slightly more than
1.0 (that gap is the house's edge), which would bias every comparison in the
market's favor.

The **value gap** for a team is simply:

```
delta = stats_probability - market_implied_probability
```

A large positive delta means the stats model is more bullish on that team
than the market; a large negative delta means the opposite. We flag anything
with `|delta| >= 0.08` (8 percentage points) as worth mentioning — this
threshold is arbitrary and easy to tune live if it's producing too many or
too few results in the demo.

## The semantic layer (vector search)

Alongside the numeric formula, each team gets a short auto-generated
`narrative` blurb (e.g. "elite two-way team on a hot streak, dominant at
home") stored in a `semantic_text` field. Elastic Serverless automatically
embeds this text with the deployment's default EIS model at index time — no
model deployment, no API keys.

This powers the `find_similar_teams` tool: a query like *"which teams are
playing lockdown defense and on a hot streak"* matches teams by the
**meaning** of their narrative, not by keyword overlap. It's a genuinely
different retrieval mechanism from the ES|QL formula above — the formula
answers "how good is this team, numerically," the semantic search answers
"which teams match this vibe/description."

Narratives are generated from a simple template over the same stats used in
the formula (see `build_narrative()` in
[ingest/fetch_nba_stats.py](../ingest/fetch_nba_stats.py)) — not an LLM call,
to keep ingestion fast and free. A stretch goal is generating richer,
less-templated blurbs with an EIS chat completion call instead.

## Explicit disclaimer

This is **analysis and insight only**. It is not betting advice, it does not
account for injuries/lineup news/travel schedule beyond what's baked into
recent form, and the weights are not fit to any validation set. Say this
plainly if asked how confident the model is.
