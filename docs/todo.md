# Todo — split across Aaron & Raymond

The split is by **layer**, not by feature, so neither person is blocked
waiting on the other's code. The key unblocker: [mappings/sample_docs.md](../mappings/sample_docs.md)
has hand-written sample documents for all three indices — Raymond can build
and test ES|QL/Agent Builder against real (if fake) data from minute one,
without waiting for Aaron's ingest scripts to actually work.

**Do this together first (~10 min), then split:**

- [ ] Both: confirm Elastic Cloud Serverless project is created, grab
      endpoint + API key, add to a shared `.env` (share via DM, not commit).
- [ ] Both: run [mappings/nba_team_stats.json](../mappings/nba_team_stats.json),
      [mappings/nba_games.json](../mappings/nba_games.json),
      [mappings/nba_odds.json](../mappings/nba_odds.json) in Dev Tools
      Console to create the indices.
- [ ] Both: run everything in [mappings/sample_docs.md](../mappings/sample_docs.md)
      so both indices have test data immediately.

Once that's done, work independently:

---

## Aaron — Data layer (ingest)

Goal: real, live data flowing into all three indices. Doesn't touch ES|QL or
Agent Builder — just gets data in with the right shape, matching the
mappings already scaffolded.

- [ ] Get a balldontlie.io API key/access confirmed working (`ingest/fetch_nba_stats.py`,
      `ingest/fetch_nba_games.py` currently stubbed — team-level win/loss/PPG
      aggregation TODO is flagged inline in `fetch_nba_stats.py`, needs
      solving: either aggregate from `nba_games` after that index is
      populated, or find a direct team-stats endpoint).
- [ ] Get The Odds API key, confirm `ingest/fetch_odds.py` returns real NBA
      events (`basketball_nba` sport key) — test with `python ingest/fetch_odds.py`
      and check the console output for indexed count.
- [ ] Verify de-vig math in `fetch_odds.py`'s `devig()` — sanity check against
      a known matchup where you know the "true" market split.
- [ ] Once `nba_games` is populated, close the loop on `fetch_nba_stats.py`'s
      TODO: derive `wins`/`losses`/`points_per_game`/`net_rating`/`last_10_*`
      by aggregating `nba_games` per team (this can be a second Python pass
      or an ES aggregation query — either is fine).
- [ ] Set up a way to re-run ingestion close to demo time so odds/stats are
      fresh (a simple `python ingest/fetch_*.py && python ingest/fetch_*.py`
      chain is enough, no need for real scheduling).
- [ ] Sanity-check final indices in Dev Tools: `GET nba_team_stats/_count`,
      `GET nba_games/_count`, `GET nba_odds/_count` — flag Raymond once
      counts look real so the demo can switch off sample data.

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
- [ ] Verify the agent actually computes the softmax conversion correctly in
      its reasoning (ask it to show its work) — tune the instructions in
      the agent config if it skips the math or hallucinates a probability.
- [ ] Chat-test the three demo prompts in [agent_builder/setup.md](../agent_builder/setup.md)
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
