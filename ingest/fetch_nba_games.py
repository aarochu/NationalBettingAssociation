"""Fetch NBA games (scheduled + completed) from balldontlie.io and index them
into `nba_games`.

balldontlie.io docs: https://docs.balldontlie.io/

Run:
    python ingest/fetch_nba_games.py
"""
import sys

import requests
from elasticsearch import helpers

from es_client import get_client

INDEX = "nba_games"
SEASON = "2025-26"
SEASON_YEAR = 2025  # balldontlie's `seasons` param takes the starting year
BASE_URL = "https://api.balldontlie.io/v1"


def fetch_games(season_year: int) -> list[dict]:
    games = []
    page_cursor = None
    while True:
        params = {"seasons[]": season_year, "per_page": 100}
        if page_cursor:
            params["cursor"] = page_cursor
        resp = requests.get(f"{BASE_URL}/games", params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        games.extend(payload["data"])
        page_cursor = payload.get("meta", {}).get("next_cursor")
        if not page_cursor:
            break
    return games


def to_record(g: dict) -> dict:
    home_score = g.get("home_team_score") or None
    away_score = g.get("visitor_team_score") or None
    status = "final" if g.get("status") == "Final" else "scheduled"

    winner = None
    if status == "final" and home_score is not None and away_score is not None:
        if home_score > away_score:
            winner = g["home_team"]["full_name"]
        elif away_score > home_score:
            winner = g["visitor_team"]["full_name"]
        else:
            winner = "draw"  # not possible in NBA, but kept for schema symmetry

    return {
        "game_id": str(g["id"]),
        "date": g["date"],
        "season": SEASON,
        "home_team": g["home_team"]["full_name"],
        "away_team": g["visitor_team"]["full_name"],
        "home_score": home_score,
        "away_score": away_score,
        "status": status,
        "winner": winner,
    }


def main():
    es = get_client()

    print(f"Fetching NBA games for season {SEASON_YEAR} from balldontlie.io ...")
    games = fetch_games(SEASON_YEAR)
    print(f"  {len(games)} games found")

    records = [to_record(g) for g in games]

    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"Deleted existing index '{INDEX}'")
    # NOTE: run mappings/nba_games.json in Dev Tools BEFORE this script for
    # the explicit mapping.

    actions = [{"_index": INDEX, "_id": r["game_id"], "_source": r} for r in records]
    success, errors = helpers.bulk(es, actions)
    es.indices.refresh(index=INDEX)
    print(f"Indexed {success} games ({len(errors)} errors)")


if __name__ == "__main__":
    sys.exit(main())
