# NationalBettingAssociation 🏀

Built for the **Elastic Rutgers Hack Night**. A stats-vs-market "value gap" finder
for NBA games: we compute a transparent, stats-based win-probability estimate from
team performance data, compare it against live sportsbook odds, and surface where
the two disagree.

> This project produces **analysis/insight only** — it is not a betting product and
> does not place, facilitate, or recommend real-money wagers.

## What it does

1. Ingests **NBA team/game stats** (stats.nba.com via [`nba_api`](https://github.com/swar/nba_api), no key needed)
   and **live NBA odds** ([The Odds API](https://the-odds-api.com/)) into Elasticsearch.
2. Computes a **stats-based win probability** per team per upcoming game using a
   documented, transparent scoring formula (see [docs/model.md](docs/model.md)) —
   no trained ML classifier, no black box.
3. Compares that estimate against the **market implied probability** derived from
   the odds, and flags games where the two diverge meaningfully.
4. Lets you **search teams by play style** using vector/semantic search over
   auto-generated team narratives.
5. Exposes all of this through an **Elastic Agent Builder** agent with custom tools,
   so you can just ask: *"Is there a value mismatch in tonight's Celtics vs Knicks
   game?"*
6. Puts it on a **local web app** with a market-board look, where every number links
   back to the ES|QL query that produced it, and the analyst chat streams the agent's
   tool calls as they run.

## Why Elasticsearch

| Feature | Where it's used |
|---|---|
| Explicit mappings | Every index (`nba_team_stats`, `nba_games`, `nba_odds`) is mapped by hand — no dynamic mapping |
| Aggregations | League context, measured home-court edge and odds coverage are ES\|QL `STATS` queries (stat tiles in the web app, `get_league_context` for the agent) |
| ES\|QL | The win-probability formula and the stats-vs-odds comparison (`LOOKUP JOIN`) are ES\|QL queries |
| Vector / semantic search | Each team has a `narrative` `semantic_text` field, embedded by ELSER on EIS — search teams by play style ("lockdown defense on a hot streak") by meaning, not keywords |
| Agent Builder | Five custom tools + one custom agent chain together to answer natural-language questions; `scripts/setup_agent.py` registers them |
| Elastic Inference Service (EIS) | Powers the agent's LLM and the narrative embeddings — no external API keys |

## Repo layout

```
app/             Local web app: FastAPI server (app/server.py) + static frontend (app/static)
ingest/          Python scripts that pull from stats.nba.com + The Odds API and bulk-index into Elasticsearch
                 (indices.py holds the index definitions; refresh_all.sh re-runs everything)
mappings/        Explicit index mapping definitions (PUT ready, paste into Dev Tools)
esql/            The win-probability formula and stats-vs-odds comparison queries
agent_builder/   Tool + agent definitions (Dev Tools Console JSON, paste-and-run)
scripts/         setup_agent.py (registers the agent), reference_model.py, verify_cluster.py
docs/            SOW, model explanation, demo script
```

## Setup

### 1. Elastic Cloud

Sign up for a free trial: https://www.elastic.co/cloud/cloud-trial-overview
(Cloud Hosted or Serverless both work — our shared deployment is Cloud Hosted 9.5).

Grab your **Elasticsearch endpoint**, **Kibana endpoint** and **API key** from the
deployment page.

### 2. The Odds API key

Sign up at https://the-odds-api.com/ (free tier) and grab your API key.

### 3. Environment variables

```bash
cp .env.example .env
# then fill in:
#   ELASTIC_ENDPOINT=
#   ELASTIC_API_KEY=
#   KIBANA_URL=        (has .kb. in the host)
#   ODDS_API_KEY=
```

`.env` is gitignored — never commit real keys.

### 4. Install dependencies

```bash
python3 -m venv .venv
.venv/bin/pip install -r ingest/requirements.txt -r app/requirements.txt
```

### 5. Create indices and run ingestion

```bash
./ingest/refresh_all.sh
```

This creates the three indices if missing (`python ingest/indices.py`), then runs,
in order: `fetch_nba_games.py` → `fetch_nba_stats.py` (aggregates team stats from
`nba_games`) → `fetch_odds.py`, and prints doc counts. Re-run it close to demo
time to refresh; each script clears its index's docs but keeps the mapping.

Each index is a versioned index behind an alias (`nba_team_stats_v1` →
`nba_team_stats`); all queries use the alias. `nba_team_stats` is a
`lookup`-mode index so `LOOKUP JOIN` works. The same definitions are in
[mappings/](mappings/) if you'd rather paste them into Dev Tools.

### 6. Register the Agent Builder tools + agent

```bash
.venv/bin/python scripts/setup_agent.py --check
```

The script reads the JSON blocks in [agent_builder/setup.md](agent_builder/setup.md),
creates or updates the five tools and the `nba_value_finder` agent through Kibana's
API, then runs each tool once. It's safe to re-run after editing setup.md. Pasting
the blocks into Dev Tools by hand still works too, with two catches the script
handles for you: new tools need `POST`, not `PUT`, and param types must be
`string`, not `keyword`.

### 7. Run the web app

```bash
./app/run.sh
```

Open http://127.0.0.1:8420 (set `PORT` to use a different one). What's on the page:

- A carousel of the five biggest gaps, each with a chart of where every sportsbook
  sits against the model.
- Stat tiles fed by ES|QL `STATS` aggregations.
- A card per priced game, sortable by gap or tip-off. Click one and the modal walks
  through the raw scores, the logistic and each book's de-vigged price.
- Power rankings, play-style semantic search, and **Under the hood**, which shows
  every query the page sent with its timing. That last section is the one to put on
  screen for judges.
- **Ask the analyst** opens a chat drawer wired to the Agent Builder agent. Answers
  can take a minute or more on big questions, so the drawer streams progress: each
  tool call appears when it starts, fills in its ES|QL and row count when it
  returns, and the answer types in after.

The Elastic and Kibana credentials stay in the Python server; the browser only talks
to `localhost`. Animations come from anime.js 4 on a CDN and turn off if the script
can't load or the viewer has reduced motion switched on.

### 8. Or chat in Kibana

Open **Kibana → Agents → NationalBettingAssociation Analyst** and try:

```
Is there a value mismatch in tonight's Celtics vs Knicks odds?
```
```
Which games tonight have the biggest gap between the market and the stats model?
```
```
Break down the win probability for the Lakers' next game.
```
```
Which teams are playing lockdown defense and on a hot streak right now?
```

## Docs

- [docs/sow.md](docs/sow.md) — scope of work, deliverables, acceptance criteria
- [docs/model.md](docs/model.md) — the win-probability formula, explained
- [docs/demo_script.md](docs/demo_script.md) — 90-second pitch script

## Non-goals

- No trained ML classifier — the "model" is a transparent, documented formula.
- No real-money betting integration of any kind.
- No custom embedding model — semantic search uses ELSER on EIS (`.elser-2-elastic`) via `semantic_text`.
