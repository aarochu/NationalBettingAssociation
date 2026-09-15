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

- [ ] Run [esql/win_probability.esql](../esql/win_probability.esql) in the
      ES|QL tab / Dev Tools, confirm it returns a ranked list against the
      sample docs.
- [ ] Run [esql/matchup_comparison.esql](../esql/matchup_comparison.esql)
      (both halves) against the sample BOS/NYK matchup, confirm both queries
      return sane rows.
- [ ] Build the three tools + agent in [agent_builder/setup.md](../agent_builder/setup.md) —
      paste the four JSON blocks into Dev Tools, or build manually in the
      Agent Builder UI if the API paths don't match your Elastic version.
- [ ] **Test `find_value_mismatches`'s `LOOKUP JOIN` first** — flagged in
      setup.md as the riskiest query (may not be available on all
      Elastic tiers/versions). If it fails, fall back to the two-tool
      approach noted in setup.md and adjust the agent instructions
      accordingly.
- [ ] Run [esql/team_narrative_search.esql](../esql/team_narrative_search.esql)
      against the sample docs — try a query with no shared keywords (e.g.
      "lockdown defense and playing hot") and confirm Celtics ranks above
      Knicks. If ES|QL `MATCH()` rejects the semantic_text field, use the
      Query DSL fallback in the same file.
- [ ] Build Tool 4 `find_similar_teams` (vector search tool) from
      [agent_builder/setup.md](../agent_builder/setup.md) and confirm the
      agent routes play-style questions to it.
- [ ] Verify the agent actually computes the softmax conversion correctly in
      its reasoning (ask it to show its work) — tune the instructions in
      the agent config if it skips the math or hallucinates a probability.
- [ ] Chat-test the four demo prompts in [agent_builder/setup.md](../agent_builder/setup.md)
      end to end against sample data.
- [ ] Refine [docs/demo_script.md](demo_script.md) based on what actually
      looks good live — cut anything that doesn't demo well in the thinking
      trace.
- [ ] Once Aaron flags that live data has landed, re-run the same three demo
      prompts against real data and sanity-check the numbers make sense
      (e.g. no team stuck at 0% from division-by-zero on `last_10_win_pct`
      if `last_10_wins + last_10_losses == 0` — guard against that in the
      agent instructions or the ES|QL if it comes up).

**You do NOT need to touch:** `ingest/`. Build entirely against sample data
until Aaron says live data is ready — the schema won't change underneath you.

---

## Merge point (last ~30-45 min)

- [ ] Both: swap sample-data queries/demo runs for live data, re-verify the
      three demo prompts still make sense.
- [ ] Both: rehearse the full demo once together, timed to ~90 seconds.
- [ ] Both: double check `.env` was never committed (`git log -p -- .env`
      should return nothing).
