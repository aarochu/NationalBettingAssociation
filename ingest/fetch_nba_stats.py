"""Derive per-team 2025-26 stats by aggregating the `nba_games` index and index
them into `nba_team_stats`.

Run fetch_nba_games.py first -- this script reads its output.

Run:
    python ingest/fetch_nba_stats.py
"""
import sys
from collections import defaultdict
from datetime import datetime, timezone

from elasticsearch import helpers
from nba_api.stats.static import teams as nba_teams

from es_client import get_client
from indices import reset_index
from teams import canonical_team

INDEX = "nba_team_stats"
GAMES_INDEX = "nba_games"
SEASON = "2025-26"

ABBREVIATIONS = {canonical_team(t["full_name"]): t["abbreviation"] for t in nba_teams.get_teams()}


def fetch_final_games(es) -> list[dict]:
    games = [
        hit["_source"]
        for hit in helpers.scan(
            es,
            index=GAMES_INDEX,
            query={"query": {"term": {"status": "final"}}},
        )
    ]
    return sorted(games, key=lambda g: g["date"])


def aggregate(games: list[dict]) -> dict[str, dict]:
    """Per-team record, scoring, home/away splits and last-10 form.

    `net_rating` is per-game point differential (points scored minus points
    allowed, per game). True net rating is per 100 possessions, which needs
    possession counts nba_games doesn't store; at NBA pace (~100 possessions
    per game) the two are within a point or so and rank teams almost
    identically, which is all the model's 0.5 weight needs.
    """
    acc = defaultdict(lambda: {
        "results": [], "points_for": 0, "points_against": 0,
        "home_w": 0, "home_g": 0, "away_w": 0, "away_g": 0,
    })
    for g in games:
        for team, pts_for, pts_against, is_home in (
            (g["home_team"], g["home_score"], g["away_score"], True),
            (g["away_team"], g["away_score"], g["home_score"], False),
        ):
            a = acc[team]
            won = g["winner"] == team
            a["results"].append(won)
            a["points_for"] += pts_for
            a["points_against"] += pts_against
            side = "home" if is_home else "away"
            a[f"{side}_g"] += 1
            a[f"{side}_w"] += won

    stats = {}
    for team, a in acc.items():
        gp = len(a["results"])
        last_10 = a["results"][-10:]
        ppg = a["points_for"] / gp
        oppg = a["points_against"] / gp
        stats[team] = {
            "games_played": gp,
            "wins": sum(a["results"]),
            "losses": gp - sum(a["results"]),
            "points_per_game": round(ppg, 1),
            "points_allowed_per_game": round(oppg, 1),
            "net_rating": round(ppg - oppg, 1),
            "home_win_pct": round(a["home_w"] / a["home_g"], 3) if a["home_g"] else 0.0,
            "away_win_pct": round(a["away_w"] / a["away_g"], 3) if a["away_g"] else 0.0,
            "last_10_wins": sum(last_10),
            "last_10_losses": len(last_10) - sum(last_10),
        }
    return stats


def _rank(stats: dict[str, dict], field: str, descending: bool = True) -> dict[str, int]:
    """1-based league rank for `field` (1 = best)."""
    ordered = sorted(stats, key=lambda t: stats[t][field], reverse=descending)
    return {team: i + 1 for i, team in enumerate(ordered)}


def build_narratives(stats: dict[str, dict]) -> dict[str, str]:
    """Generate a short natural-language blurb per team describing its form and
    play style. This is what gets indexed into the `narrative` semantic_text
    field and embedded by ELSER at index time.

    Buckets are league-relative ranks rather than fixed thresholds: a fixed
    cutoff like "net_rating >= 8" puts most of the league in one bucket in a
    typical season, which makes every blurb read the same and semantic search
    useless. Ranking guarantees the spread. Still a template, not an LLM call,
    so ingestion stays fast and free.
    """
    n = len(stats)
    overall = _rank(stats, "net_rating")
    offense = _rank(stats, "points_per_game")
    defense = _rank(stats, "points_allowed_per_game", descending=False)
    top, bottom = n // 5, n - n // 5  # top/bottom ~20% get a strong descriptor

    narratives = {}
    for team, s in stats.items():
        r = overall[team]
        if r <= 5:
            form = "Elite title contender dominating on both ends"
        elif r <= 12:
            form = "Strong playoff-caliber team"
        elif r <= 18:
            form = "Middle-of-the-pack team with an inconsistent identity"
        elif r <= 24:
            form = "Below-average team that struggles to close out games"
        else:
            form = "Rebuilding team losing badly most nights"

        if offense[team] <= top:
            off = "a high-powered, explosive offense"
        elif offense[team] > bottom:
            off = "a stagnant offense that struggles to score"
        else:
            off = "an average offense"

        if defense[team] <= top:
            dfn = "lockdown defense"
        elif defense[team] > bottom:
            dfn = "porous defense that gives up easy points"
        else:
            dfn = "middling defense"

        w10 = s["last_10_wins"]
        if w10 >= 8:
            streak = f"red-hot to finish the season, winning {w10} of its last 10"
        elif w10 == 0:
            streak = "ice cold down the stretch, winless in its last 10"
        elif w10 <= 3:
            streak = f"ice cold down the stretch, winning only {w10} of its last 10"
        else:
            streak = f"went {w10}-{s['last_10_losses']} over its last 10"

        if s["home_win_pct"] >= 0.7:
            home = "dominant at home"
        elif s["home_win_pct"] < 0.45:
            home = "shaky even at home"
        else:
            home = "steady at home"

        narratives[team] = (
            f"{form} ({s['wins']}-{s['losses']}), with {off} and {dfn}; "
            f"{streak}, {home}."
        )
    return narratives


def main():
    es = get_client()

    print(f"Aggregating team stats from '{GAMES_INDEX}' ...")
    games = fetch_final_games(es)
    if not games:
        raise RuntimeError(f"No final games in '{GAMES_INDEX}'. Run fetch_nba_games.py first.")
    stats = aggregate(games)
    narratives = build_narratives(stats)
    print(f"  {len(games)} games -> {len(stats)} teams")

    now = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "team_id": ABBREVIATIONS[team],
            "team": team,
            "team_abbreviation": ABBREVIATIONS[team],
            "season": SEASON,
            "last_updated": now,
            **s,
            "narrative": narratives[team],
        }
        for team, s in stats.items()
    ]

    reset_index(es, INDEX)
    actions = [{"_index": INDEX, "_id": r["team_id"], "_source": r} for r in records]
    success, errors = helpers.bulk(es, actions)
    es.indices.refresh(index=INDEX)
    print(f"Indexed {success} team records ({len(errors)} errors)")


if __name__ == "__main__":
    sys.exit(main())
