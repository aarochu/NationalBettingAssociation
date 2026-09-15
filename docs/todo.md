# Todo — split across Aaron & Raymond

The split is by **layer**, not by feature, so neither person is blocked
waiting on the other's code. The key unblocker: [mappings/sample_docs.md](../mappings/sample_docs.md)
has hand-written sample documents for all three indices — Raymond can build
and test ES|QL/Agent Builder against real (if fake) data from minute one,
without waiting for Aaron's ingest scripts to actually work.

**Do this together first (~10 min), then split:**

- [x] Both: confirm Elastic Cloud project is created, grab
      endpoint + API key, add to a shared `.env` (share via DM, not commit).
      _Done — it's Cloud Hosted 9.5.3, not Serverless; works the same for us._
- [x] Both: create the indices. _Done via `python ingest/indices.py`
      (versioned index + alias, `nba_team_stats` in `lookup` mode so
      `LOOKUP JOIN` works, `narrative` pinned to `.elser-2-elastic`)._
- [x] ~~Both: run everything in [mappings/sample_docs.md](../mappings/sample_docs.md)~~
      _Skipped — live data landed first, so there's no need for sample docs.
      Loading them now would overwrite the real BOS/NYK rows._

Once that's done, work independently:

---

## Aaron — Data layer (ingest)

Goal: real, live data flowing into all three indices. Doesn't touch ES|QL or
Agent Builder — just gets data in with the right shape, matching the
mappings already scaffolded.

- [x] ~~Get a balldontlie.io API key~~ — balldontlie now returns 401 without
      a key, so `fetch_nba_games.py` uses stats.nba.com via `nba_api` instead
      (free, no key). All 1230 games of the 2025-26 regular season, including
      the 5 neutral-site games that list both teams as away. Those are flagged
      `neutral_site` and left out of home/away splits, matching the official
      standings.
- [x] The Odds API key works — `fetch_odds.py` indexed 190 records (41 events,
      5 bookmakers). Events are 2026-27 season games starting 2026-10-20.
      Odds API names are canonical for `team`. `ingest/teams.py` maps
      stats.nba.com's "LA Clippers" → "Los Angeles Clippers".
- [x] De-vig math verified: -110/-110 → 50/50, -200/+170 → 64.3/35.7, and
      every live bookmaker/game pair sums to exactly 1.0. (Fixed
      `sample_docs.md`, which had the *raw* vigged probabilities.)
- [x] `fetch_nba_stats.py` TODO closed — it aggregates `nba_games` per team
      (record, PPG/opp PPG, home/away win %, last 10). `net_rating` = per-game
      point differential (see docs/model.md). Stats are end-of-2025-26 and
      serve as priors for the 2026-27 games in the odds.
- [x] Narratives: switched fixed thresholds to league-relative ranks
      (offense/defense top/bottom 20%, net-rating tiers). All 30 blurbs are
      distinct.
- [x] Re-run ingestion: `./ingest/refresh_all.sh` (ensures indices → games →
      stats → odds → prints counts). Uses 1 Odds API request per run.
- [x] Counts: `nba_team_stats` 30, `nba_games` 1230, `nba_odds` 190.
      **Raymond: live data has landed, so build against it directly.**
      Also verified on live data: the `find_value_mismatches` `LOOKUP JOIN`
      works through the alias with 0 unmatched odds rows, and
      `team_narrative_search` "lockdown defense and playing hot" ranks
      Pistons, Celtics, Rockets above the Knicks.

**Fixed along the way:** the ingest scripts used to delete their index before
indexing. The re-created index got dynamic mappings, losing
`semantic_text` and lookup mode. They now clear docs with
`reset_index()` in `ingest/indices.py` instead.

**You do NOT need to touch:** `esql/`, `agent_builder/`. Those are built and
tested against the sample docs — swapping in live data later should require
zero changes on Raymond's side since the document shape is identical.

---

## Raymond — Model + Agent layer

Goal: the win-probability formula, the comparison logic, and the working
Agent Builder agent, built and demoable entirely against the sample docs in
[mappings/sample_docs.md](../mappings/sample_docs.md) — no dependency on
Aaron's ingest scripts working.

### Written and self-checked — needs a cluster to confirm

Everything below is committed and verified as far as it can be without an
Elastic endpoint. What's left on each is pasting it in and watching it run.

- [x] **Fixed the softmax saturation bug.** The formula as originally
      specified returned **100.0%** for Boston on the sample matchup — an
      unscaled `exp(a)/(exp(a)+exp(b))` over score gaps of ~16 pins every
      game at 0% or 100%, so every delta would have been garbage and the
      demo visibly broken. The conversion now divides the score gap by a
      scale of 10, giving Boston 83.1%. Worked through with the tuning table
      in [docs/model.md](model.md#calibrating-the-conversion).
- [x] **Fixed the de-vig assumption.** The agent instructions claimed
      `implied_probability` was "already de-vigged"; the sample docs sum to
      **1.045**, so it isn't. The agent now normalizes defensively before
      comparing (a no-op once ingest de-vigs at write time). Tell that it's
      working: the two teams' deltas come out as exact mirrors,
      +22.2pp / −22.2pp.
- [x] **Implemented the home-court bonus.** `docs/model.md` specified +5 but
      no query applied it. Now applied wherever there's game context
      (`matchup_comparison.esql` query C, `value_mismatches.esql`,
      `find_value_mismatches`). `get_stats_prediction` still returns a
      neutral-court score by design — it takes a team, not a game — and the
      agent instructions tell the agent to add the +5 itself and say so.
- [x] **Guarded the `last_10_win_pct` division by zero** (was the last item
      on this list — done up front instead, since it's a one-line `CASE` and
      a null score silently drops a team from the ranking). Falls back to
      0.5, "no information, treat as average", rather than 0.0. Applied in
      every query and mirrored in the reference model.
- [x] Added [scripts/reference_model.py](../scripts/reference_model.py) — a
      dependency-free reference implementation that prints the expected
      numbers for the sample matchup. This is how you check the agent's
      arithmetic instead of eyeballing the thinking trace. Run it right
      before the demo: `python3 scripts/reference_model.py`
- [x] Added [esql/value_mismatches.esql](../esql/value_mismatches.esql) —
      the cross-game query behind the "biggest gap" demo prompt existed only
      inside the tool JSON, so it couldn't be debugged in Dev Tools. Now
      standalone, with a commented no-join fallback.
- [x] Rewrote the agent instructions: explicit three-step math (score →
      scaled logistic → de-vig), a worked example with the expected numbers,
      a self-check ("if you computed >97%, you dropped the divisor"), and
      firmer no-betting-advice framing.
- [x] **Fixed the semantic search ranking.** `find_similar_teams` and
      `team_narrative_search.esql` both ended with `SORT net_rating DESC`,
      which discards the relevance ordering — the tool returned teams by how
      good they are, not how well they matched the description. It also made
      the suggested test unfalsifiable: Boston outranks New York on
      `net_rating` whether or not semantic search did anything. Now uses
      `METADATA _score | SORT _score DESC`, and the .esql file has an
      inverted-meaning second query that actually distinguishes a working
      embedding from a keyword fallback.
- [x] **Closed a missed hard requirement.** sow.md requirement 4(a) is
      "must demonstrate aggregations", and nothing in the project did —
      team rollups run in Python via defaultdict, and there was no ES|QL
      `STATS` or Query DSL `aggs` anywhere. Added
      [esql/league_aggregates.esql](../esql/league_aggregates.esql) (league
      context, measured home-court edge, grouped scoring tiers, per-game
      bookmaker spread) and a `get_league_context` agent tool so an
      aggregation actually appears in the demo.
- [x] Refined [docs/demo_script.md](demo_script.md) — Beat 3 now lists the
      expected output (Boston 83%, market 61%, +22pp) and the two failure
      modes to catch live.

### Still needs the live cluster

- [ ] Run [esql/win_probability.esql](../esql/win_probability.esql) in the
      ES|QL tab / Dev Tools, confirm it returns a ranked list against the
      sample docs.
- [ ] Run [esql/matchup_comparison.esql](../esql/matchup_comparison.esql)
      (all three queries — A and B are the diagnostic halves, C is the joined
      version the demo uses) against the sample BOS/NYK matchup.
- [ ] Build the three tools + agent in [agent_builder/setup.md](../agent_builder/setup.md) —
      paste the JSON blocks into Dev Tools, or build manually in the
      Agent Builder UI if the API paths don't match your Elastic version.
- [x] **`LOOKUP JOIN` root cause found and now fixed upstream.** It only
      targets lookup-mode indices, and the original mapping created an
      ordinary one. `ingest/indices.py` now creates `nba_team_stats` in
      lookup mode behind an alias, and Aaron confirmed the join works on
      live data, so the mirror index I'd written is no longer needed and
      has been removed from setup.md.
- [ ] Test the `get_market_odds` `OR` param — some Agent Builder versions
      require every declared `?param` on every call, so "optional if the
      other is given" may not hold. Noted inline in setup.md with the fix.
- [ ] Ask the agent to show its work and check it against
      `scripts/reference_model.py`. Specifically: did it use the `/10`
      divisor, and are the two deltas exact mirrors? Those are the two
      things it's most likely to silently get wrong.
- [ ] Run [esql/team_narrative_search.esql](../esql/team_narrative_search.esql)
      against the sample docs. **Use the `_score` version, not the committed
      one** — see the vector-search note below; the committed query sorts by
      `net_rating`, which throws the semantic ranking away and makes the test
      unable to fail.
- [ ] Build Tool 4 `find_similar_teams` from
      [agent_builder/setup.md](../agent_builder/setup.md) and confirm the
      agent routes play-style questions to it rather than guessing at a stat
      field.
- [ ] Run [esql/league_aggregates.esql](../esql/league_aggregates.esql). Check
      `avg_net_rating` comes back ~0.0 — if it doesn't, ingest has
      double-counted or dropped games and every probability downstream is
      suspect.
- [ ] Build Tool 5 `get_league_context` and confirm the agent uses it to
      frame numbers rather than quoting them bare.
- [ ] Chat-test the four demo prompts in [agent_builder/setup.md](../agent_builder/setup.md)
      end to end against sample data.
- [ ] Once Aaron flags that live data has landed, re-run the three demo
      prompts against real data. Sanity-check that probabilities land in a
      believable spread rather than clustering at the extremes — if a lot of
      games come back in the 90s, the scale divisor needs raising. The table
      in [docs/model.md](model.md#calibrating-the-conversion) shows the
      effect of each value; it's a one-constant change in four places
      (model.md, the agent instructions, reference_model.py, demo_script.md).

**You do NOT need to touch:** `ingest/`. Build entirely against sample data
until Aaron says live data is ready — the schema won't change underneath you.

---

## Merge point (last ~30-45 min)

- [ ] Both: swap sample-data queries/demo runs for live data, re-verify the
      three demo prompts still make sense.
- [ ] Both: rehearse the full demo once together, timed to ~90 seconds.
- [ ] Both: double check `.env` was never committed (`git log -p -- .env`
      should return nothing).
