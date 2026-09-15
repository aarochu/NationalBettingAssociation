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
| `net_rating` | Points scored minus points allowed **per game** (the simplified version of the per-100-possessions stat; `nba_games` doesn't store possessions, and at ~100 possessions/game the two are within about a point) — the single best proxy for "how good is this team right now." Currently spans +11.1 (OKC) to −12.0 (WAS). |
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
P(team_a wins) = 1 / (1 + exp(-(raw_score_a - raw_score_b) / SCALE))
P(team_b wins) = 1 - P(team_a wins)

SCALE = 10
```

This is the two-class softmax `exp(a) / (exp(a) + exp(b))`, rewritten in the
equivalent logistic form so the scale divisor is visible and tunable. Both
forms guarantee the probabilities sum to 1.0.

### Calibrating the conversion

**The `SCALE` divisor is not optional.** The unscaled softmax — the version
this doc originally specified — saturates on real inputs. Worked through on
the sample BOS/NYK matchup:

| | net_rating × 0.5 | form × 30 | home | raw_score |
|---|---|---|---|---|
| Boston (home) | 6.10 | 24.00 | +5 | **35.10** |
| New York | 1.15 | 18.00 | 0 | **19.15** |

A gap of 15.95 through an unscaled softmax gives Boston **100.0%**. Not
99-point-something — 100.0% to four decimal places. Every game would read as
a gigantic mismatch against the market, the deltas would all be meaningless,
and the demo would be visibly broken the first time anyone looked at a number.

The cause is a units mismatch. `raw_score` lives on a scale where one "point"
is a fraction of a point of net rating, but `exp()` treats a gap of 16 as
astronomically decisive. Dividing the gap by `SCALE` puts it back in a range
where the logistic behaves:

| SCALE | P(Boston) |
|---|---|
| 1 (unscaled) | 100.0% |
| 5 | 96.0% |
| 6.5 | 92.1% |
| **10** | **83.1%** |
| 15 | 74.3% |
| 20 | 68.9% |

`SCALE = 10` is the pick. It's a judgment call, not a fit: it keeps a strong
favorite in the 80s rather than pinned at 100%, and leaves room for a genuine
blowout matchup to reach the 90s. For reference, NBA point spreads convert to
win probability at roughly `spread / 6.5` — our divisor is larger because
`raw_score` is inflated relative to points by the `× 30` recency term.

Like the weights, this is tunable live. `scripts/reference_model.py` prints
the table above on every run, so if the demo numbers look too confident or too
timid, change one constant and re-run.

## Comparing against the market

The market's "implied probability" comes from converting sportsbook decimal
odds (`1 / odds_decimal`) and then **removing the vig** (bookmaker margin) by
normalizing both teams' implied probabilities to sum to 1.0 — see
`devig()` in [ingest/fetch_odds.py](../ingest/fetch_odds.py). Without this
step, both teams' raw implied probabilities would sum to slightly more than
1.0 (that gap is the house's edge), which would bias every comparison in the
market's favor.

**Don't assume the stored value is already de-vigged.** The
`implied_probability` field in the sample docs is raw `1 / odds_decimal`:
0.637 and 0.408, summing to 1.045. So the agent normalizes defensively before
comparing, and normalizing twice is a no-op, so this stays correct once
ingest starts de-vigging at write time. A quick tell that it's working: the
two teams' deltas should be exact mirrors (+22.2pp / −22.2pp). If they aren't,
the market side didn't sum to 1.0.

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
home") stored in a `semantic_text` field. Elasticsearch automatically
embeds this text at index time with ELSER running on EIS
(`.elser-2-elastic`) — no model deployment, no API keys.

This powers the `find_similar_teams` tool: a query like *"which teams are
playing lockdown defense and on a hot streak"* matches teams by the
**meaning** of their narrative, not by keyword overlap. It's a genuinely
different retrieval mechanism from the ES|QL formula above — the formula
answers "how good is this team, numerically," the semantic search answers
"which teams match this vibe/description."

Narratives are generated from a simple template over the same stats used in
the formula (see `build_narratives()` in
[ingest/fetch_nba_stats.py](../ingest/fetch_nba_stats.py)) — not an LLM call,
to keep ingestion fast and free. Buckets are league-relative ranks (top/bottom
~20% for offense and defense, net-rating tiers) rather than fixed thresholds,
so every team gets a distinct blurb. A stretch goal is generating richer,
less-templated blurbs with an EIS chat completion call instead.

## Explicit disclaimer

This is **analysis and insight only**. It is not betting advice, it does not
account for injuries/lineup news/travel schedule beyond what's baked into
recent form, and the weights are not fit to any validation set. Say this
plainly if asked how confident the model is.
