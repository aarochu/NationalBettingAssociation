# NationalBettingAssociation 🏀

Built for the **Elastic Rutgers Hack Night**. A stats-vs-market "value gap" finder
for NBA games: we compute a transparent, stats-based win-probability estimate from
team performance data, compare it against live sportsbook odds, and surface where
the two disagree.

> This project produces **analysis/insight only** — it is not a betting product and
> does not place, facilitate, or recommend real-money wagers.

## What it does

1. Ingests **NBA team/game stats** ([balldontlie.io](https://www.balldontlie.io/) API)
   and **live NBA odds** ([The Odds API](https://the-odds-api.com/)) into Elasticsearch.
2. Computes a **stats-based win probability** per team per upcoming game using a
   documented, transparent scoring formula (see [docs/model.md](docs/model.md)) —
   no trained ML classifier, no black box.
3. Compares that estimate against the **market implied probability** derived from
   the odds, and flags games where the two diverge meaningfully.
4. Exposes all of this through an **Elastic Agent Builder** agent with custom tools,
   so you can just ask: *"Is there a value mismatch in tonight's Celtics vs Knicks
   game?"*

## Why Elasticsearch

| Feature | Where it's used |
|---|---|
| Explicit mappings | Every index (`nba_team_stats`, `nba_games`, `nba_odds`) is mapped by hand — no dynamic mapping |
| Aggregations | Recent form / rolling stats computed via ES aggregations |
| ES\|QL | The win-probability formula and the stats-vs-odds comparison are ES\|QL queries |
| Agent Builder | Three custom tools + one custom agent chain together to answer natural-language questions |
| Elastic Inference Service (EIS) | Powers the agent's LLM — no external API keys |

## Repo layout

```
ingest/          Python scripts that pull from balldontlie.io + The Odds API and bulk-index into Elasticsearch
mappings/        Explicit index mapping definitions (PUT ready, paste into Dev Tools)
esql/            The win-probability formula and stats-vs-odds comparison queries
agent_builder/   Tool + agent definitions (Dev Tools Console JSON, paste-and-run)
docs/            SOW, model explanation, demo script
```

## Setup

### 1. Elastic Cloud Serverless

Sign up for a free trial project: https://www.elastic.co/cloud/cloud-trial-overview

Grab your **Elasticsearch endpoint** and **API key** from your project's Connection
Details page.

### 2. The Odds API key

Sign up at https://the-odds-api.com/ (free tier) and grab your API key.

### 3. Environment variables

```bash
cp .env.example .env
# then fill in:
#   ELASTIC_ENDPOINT=
#   ELASTIC_API_KEY=
#   ODDS_API_KEY=
```

`.env` is gitignored — never commit real keys.

### 4. Install dependencies

```bash
pip install -r ingest/requirements.txt
```

### 5. Create indices

Paste each file in [mappings/](mappings/) into Kibana's **Dev Tools Console**
(hamburger menu → Management → Dev Tools) and run it. This creates
`nba_team_stats`, `nba_games`, and `nba_odds` with explicit field types.

### 6. Run ingestion

```bash
python ingest/fetch_nba_stats.py
python ingest/fetch_nba_games.py
python ingest/fetch_odds.py
```

Re-run any of these to refresh — each script recreates its index so there are no
duplicates.

### 7. Build the Agent Builder tools + agent

In your Elastic Serverless project, go to **Agents**. Paste the four blocks in
[agent_builder/setup.md](agent_builder/setup.md) (three tools + one agent) into
Dev Tools Console, or follow the manual walkthrough in the same file.

### 8. Chat with it

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

## Docs

- [docs/sow.md](docs/sow.md) — scope of work, deliverables, acceptance criteria
- [docs/model.md](docs/model.md) — the win-probability formula, explained
- [docs/demo_script.md](docs/demo_script.md) — 90-second pitch script

## Non-goals

- No trained ML classifier — the "model" is a transparent, documented formula.
- No real-money betting integration of any kind.
- No custom embedding model — EIS defaults only, if semantic search is added as a stretch goal.
