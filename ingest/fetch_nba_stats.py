"""Fetch current-season NBA team stats from balldontlie.io and index them into
`nba_team_stats`.

balldontlie.io docs: https://docs.balldontlie.io/
Free tier does not require an API key for the /teams and /season_averages
style endpoints used here, but the API has evolved -- check the current docs
if endpoints below 404.

Run:
    python ingest/fetch_nba_stats.py
"""
import sys
from datetime import date, datetime, timezone

import requests
from elasticsearch import helpers

from es_client import get_client

INDEX = "nba_team_stats"
SEASON = "2025-26"
BASE_URL = "https://api.balldontlie.io/v1"


def fetch_teams() -> list[dict]:
    resp = requests.get(f"{BASE_URL}/teams", timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]


def fetch_team_record(team_id: int) -> dict:
    """Placeholder aggregation call.

    TODO(Aaron/Raymond): balldontlie's stats/season_averages endpoints are
    player-level, not team-level. Team win/loss + PPG splits need to be
    derived by aggregating `nba_games` (see fetch_nba_games.py) once that
    index is populated, OR pulled from a secondary source (e.g.
    stats.nba.com via nba_api) if a direct team-stats endpoint isn't
    available on the free tier. Wire this up once nba_games has real data --
    until then this returns placeholder zeros so the pipeline runs
    end-to-end and the index has the right shape.
    """
    return {
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "points_per_game": 0.0,
        "points_allowed_per_game": 0.0,
        "net_rating": 0.0,
        "home_win_pct": 0.0,
        "away_win_pct": 0.0,
        "last_10_wins": 0,
        "last_10_losses": 0,
    }


def build_narrative(stats: dict) -> str:
    """Generate a short natural-language blurb describing the team's current
    form/play style from its stats. This is what gets indexed into the
    `narrative` semantic_text field -- Elastic auto-embeds it with the
    deployment's default EIS model at index time, no model setup needed.

    This is a simple template, not an LLM call -- keeps ingestion fast and
    free. A stretch goal is generating these with an EIS chat completion
    call instead (see eis_guide.md section 3) for richer, less templated
    text, but templated text embeds and searches just as well for the demo.
    """
    net_rating = stats["net_rating"]
    last_10_wins = stats["last_10_wins"]
    last_10_losses = stats["last_10_losses"]
    home_win_pct = stats["home_win_pct"]

    if net_rating >= 8:
        form = "Elite two-way team playing at a dominant level"
    elif net_rating >= 2:
        form = "Solid, above-average team"
    elif net_rating >= -2:
        form = "Middle-of-the-pack team with an inconsistent identity"
    else:
        form = "Struggling team, below-average on both ends"

    if last_10_wins >= 8:
        streak = "on a hot streak over its last 10 games"
    elif last_10_wins >= 5:
        streak = "with a roughly even record over its last 10 games"
    else:
        streak = "in a rough stretch over its last 10 games"

    home_note = (
        "dominant at home" if home_win_pct >= 0.7
        else "shaky at home" if home_win_pct < 0.5
        else "steady at home"
    )

    return f"{form}, {streak}, {home_note}."


def build_records(teams: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    records = []
    for t in teams:
        team_stats = fetch_team_record(t["id"])
        record = {
            "team_id": t["abbreviation"],
            "team": t["full_name"],
            "team_abbreviation": t["abbreviation"],
            "season": SEASON,
            "last_updated": now,
            **team_stats,
            "narrative": build_narrative(team_stats),
        }
        records.append(record)
    return records


def main():
    es = get_client()

    print("Fetching NBA teams from balldontlie.io ...")
    teams = fetch_teams()
    print(f"  {len(teams)} teams found")

    records = build_records(teams)

    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"Deleted existing index '{INDEX}'")
    # NOTE: run mappings/nba_team_stats.json in Dev Tools BEFORE this script
    # if you want the explicit mapping. Re-running this script after a
    # dynamic-mapped index was created will not retroactively fix types --
    # delete the index and re-run the PUT mapping first.

    actions = [{"_index": INDEX, "_id": r["team_id"], "_source": r} for r in records]
    success, errors = helpers.bulk(es, actions)
    es.indices.refresh(index=INDEX)
    print(f"Indexed {success} team records ({len(errors)} errors)")


if __name__ == "__main__":
    sys.exit(main())
