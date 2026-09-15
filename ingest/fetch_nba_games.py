"""Fetch completed NBA regular-season games from stats.nba.com (via the
`nba_api` package) and index them into `nba_games`.

balldontlie.io was the original source, but it now requires an API key for
every endpoint. stats.nba.com is free and returns team-level game logs
directly, which is also what fetch_nba_stats.py aggregates from.

Run:
    python ingest/fetch_nba_games.py
"""
import sys

from elasticsearch import helpers
from nba_api.stats.endpoints import leaguegamelog

from es_client import get_client
from indices import reset_index
from teams import canonical_team

INDEX = "nba_games"
SEASON = "2025-26"


def fetch_team_game_log(season: str) -> list[dict]:
    """One row per team per game (so two rows per game)."""
    log = leaguegamelog.LeagueGameLog(
        season=season,
        season_type_all_star="Regular Season",
        player_or_team_abbreviation="T",
        timeout=60,
    )
    return log.get_normalized_dict()["LeagueGameLog"]


def to_records(rows: list[dict]) -> list[dict]:
    by_game: dict[str, list[dict]] = {}
    for row in rows:
        by_game.setdefault(row["GAME_ID"], []).append(row)

    records = []
    for game_id, pair in by_game.items():
        if len(pair) != 2:
            continue
        # MATCHUP is "BOS vs. NYK" for the home team, "NYK @ BOS" for away.
        # Neutral-site games (international, NBA Cup knockouts) list BOTH
        # teams with "@"; treat the first row's opponent as the home team.
        home = next((r for r in pair if " vs. " in r["MATCHUP"]), None)
        if home is None:
            home = pair[1]
        away = pair[0] if home is pair[1] else pair[1]
        home_team = canonical_team(home["TEAM_NAME"])
        away_team = canonical_team(away["TEAM_NAME"])
        records.append(
            {
                "game_id": game_id,
                "date": home["GAME_DATE"],
                "season": SEASON,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home["PTS"],
                "away_score": away["PTS"],
                "status": "final",
                "winner": home_team if home["WL"] == "W" else away_team,
            }
        )
    return records


def main():
    es = get_client()

    print(f"Fetching {SEASON} NBA games from stats.nba.com ...")
    rows = fetch_team_game_log(SEASON)
    records = to_records(rows)
    print(f"  {len(records)} games found")

    reset_index(es, INDEX)
    actions = [{"_index": INDEX, "_id": r["game_id"], "_source": r} for r in records]
    success, errors = helpers.bulk(es, actions)
    es.indices.refresh(index=INDEX)
    print(f"Indexed {success} games ({len(errors)} errors)")


if __name__ == "__main__":
    sys.exit(main())
