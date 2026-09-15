# Sample documents

Paste these into Dev Tools Console to have working data in all three indices
**before** the ingest scripts are finished. This lets whoever is building
ES|QL queries or Agent Builder tools work against a real, populated index
without waiting on the other person's ingestion code.

Run [nba_team_stats.json](nba_team_stats.json), [nba_games.json](nba_games.json),
and [nba_odds.json](nba_odds.json) first to create the indices, then run these.

## nba_team_stats

```
POST nba_team_stats/_doc
{
  "team_id": "BOS",
  "team": "Boston Celtics",
  "team_abbreviation": "BOS",
  "season": "2025-26",
  "games_played": 10,
  "wins": 8,
  "losses": 2,
  "points_per_game": 118.4,
  "points_allowed_per_game": 106.2,
  "net_rating": 12.2,
  "home_win_pct": 0.83,
  "away_win_pct": 0.75,
  "last_10_wins": 8,
  "last_10_losses": 2,
  "last_updated": "2026-09-14",
  "narrative": "Elite two-way team on a hot streak, dominant at home, elite perimeter defense and efficient three-point shooting."
}
```

```
POST nba_team_stats/_doc
{
  "team_id": "NYK",
  "team": "New York Knicks",
  "team_abbreviation": "NYK",
  "season": "2025-26",
  "games_played": 10,
  "wins": 6,
  "losses": 4,
  "points_per_game": 112.1,
  "points_allowed_per_game": 109.8,
  "net_rating": 2.3,
  "home_win_pct": 0.67,
  "away_win_pct": 0.5,
  "last_10_wins": 6,
  "last_10_losses": 4,
  "last_updated": "2026-09-14",
  "narrative": "Inconsistent form, streaky shooting, solid interior defense but struggles on the road against top offenses."
}
```

## nba_games

```
POST nba_games/_doc
{
  "game_id": "2026-09-20-BOS-NYK",
  "date": "2026-09-20",
  "season": "2025-26",
  "home_team": "Boston Celtics",
  "away_team": "New York Knicks",
  "home_score": null,
  "away_score": null,
  "status": "scheduled",
  "winner": null
}
```

## nba_odds

```
POST nba_odds/_doc
{
  "game_id": "2026-09-20-BOS-NYK",
  "date": "2026-09-20",
  "home_team": "Boston Celtics",
  "away_team": "New York Knicks",
  "bookmaker": "draftkings",
  "market": "h2h",
  "team": "Boston Celtics",
  "odds_decimal": 1.57,
  "implied_probability": 0.637,
  "fetched_at": "2026-09-14T20:00:00"
}
```

```
POST nba_odds/_doc
{
  "game_id": "2026-09-20-BOS-NYK",
  "date": "2026-09-20",
  "home_team": "Boston Celtics",
  "away_team": "New York Knicks",
  "bookmaker": "draftkings",
  "market": "h2h",
  "team": "New York Knicks",
  "odds_decimal": 2.45,
  "implied_probability": 0.408,
  "fetched_at": "2026-09-14T20:00:00"
}
```

After running these, `_refresh` both indices so the docs are immediately
searchable:

```
POST nba_team_stats/_refresh
POST nba_games/_refresh
POST nba_odds/_refresh
```
