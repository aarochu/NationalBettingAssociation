"""Fetch live NBA moneyline odds from The Odds API and index them into
`nba_odds`, converting decimal odds to de-vigged implied probability.

The Odds API docs: https://the-odds-api.com/liveapi/guides/v4/

Run:
    python ingest/fetch_odds.py
"""
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from elasticsearch import helpers

from es_client import get_client

load_dotenv()

INDEX = "nba_odds"
SPORT_KEY = "basketball_nba"
BASE_URL = "https://api.the-odds-api.com/v4"


def fetch_odds(api_key: str) -> list[dict]:
    resp = requests.get(
        f"{BASE_URL}/sports/{SPORT_KEY}/odds",
        params={
            "apiKey": api_key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "decimal",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove bookmaker overround (vig) by normalizing implied probabilities
    so they sum to 1.0.
    """
    total = prob_a + prob_b
    if total == 0:
        return 0.0, 0.0
    return prob_a / total, prob_b / total


def to_records(events: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    records = []

    for event in events:
        game_id = event["id"]
        home_team = event["home_team"]
        away_team = event["away_team"]
        date = event["commence_time"]

        for bookmaker in event.get("bookmakers", []):
            h2h = next(
                (m for m in bookmaker["markets"] if m["key"] == "h2h"), None
            )
            if not h2h:
                continue

            outcomes = {o["name"]: o["price"] for o in h2h["outcomes"]}
            if home_team not in outcomes or away_team not in outcomes:
                continue

            raw_prob_home = 1.0 / outcomes[home_team]
            raw_prob_away = 1.0 / outcomes[away_team]
            prob_home, prob_away = devig(raw_prob_home, raw_prob_away)

            for team, odds_decimal, implied_prob in (
                (home_team, outcomes[home_team], prob_home),
                (away_team, outcomes[away_team], prob_away),
            ):
                records.append(
                    {
                        "game_id": game_id,
                        "date": date,
                        "home_team": home_team,
                        "away_team": away_team,
                        "bookmaker": bookmaker["key"],
                        "market": "h2h",
                        "team": team,
                        "odds_decimal": odds_decimal,
                        "implied_probability": round(implied_prob, 4),
                        "fetched_at": now,
                    }
                )

    return records


def main():
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ODDS_API_KEY not set. Copy .env.example to .env and fill it in."
        )

    es = get_client()

    print("Fetching NBA odds from The Odds API ...")
    events = fetch_odds(api_key)
    print(f"  {len(events)} events found")

    records = to_records(events)

    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"Deleted existing index '{INDEX}'")
    # NOTE: run mappings/nba_odds.json in Dev Tools BEFORE this script for
    # the explicit mapping.

    actions = [{"_index": INDEX, "_source": r} for r in records]
    success, errors = helpers.bulk(es, actions) if actions else (0, [])
    es.indices.refresh(index=INDEX)
    print(f"Indexed {success} odds records ({len(errors)} errors)")


if __name__ == "__main__":
    sys.exit(main())
