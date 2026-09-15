"""Canonical team names.

`team` is the join key between nba_odds and nba_team_stats (LOOKUP JOIN ON
team), so every source must emit the same spelling. The Odds API's full names
are canonical; stats.nba.com differs only for the Clippers.
"""

_ALIASES = {
    "LA Clippers": "Los Angeles Clippers",
}


def canonical_team(name: str) -> str:
    return _ALIASES.get(name, name)
