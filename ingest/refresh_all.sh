#!/usr/bin/env bash
# Re-run all ingestion close to demo time so odds and stats are fresh.
# Order matters: team stats are aggregated from nba_games.
# Each run of fetch_odds.py uses 1 request of The Odds API quota.
#
#   ./ingest/refresh_all.sh
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-../.venv/bin/python}"

"$PY" indices.py
"$PY" fetch_nba_games.py
"$PY" fetch_nba_stats.py
"$PY" fetch_odds.py

"$PY" -W ignore -c '
from es_client import get_client
es = get_client()
for i in ("nba_team_stats", "nba_games", "nba_odds"):
    print(i + ":", es.count(index=i)["count"], "docs")
'
