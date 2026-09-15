"""Index definitions shared by every ingest script.

Each index is created under a versioned name (e.g. `nba_team_stats_v1`) with
an alias under the plain name (`nba_team_stats`). Everything else -- ingest,
ES|QL, Agent Builder -- only ever uses the alias, so a mapping change is a
new `_v2` index + alias swap instead of breaking every query.

Ingest scripts call `reset_index()`, which creates the index if missing and
otherwise clears its documents. They must NOT delete and re-create the index
by name: a bulk write into a missing index creates it with dynamic mappings,
silently dropping `index.mode: lookup` and the `semantic_text` field.

Run directly to create all three indices:
    python ingest/indices.py
"""
from elasticsearch import Elasticsearch

VERSION = "v1"

# `.elser-2-elastic` is ELSER served by the Elastic Inference Service (EIS):
# no ML nodes needed. Pinned explicitly because the default inference endpoint
# for semantic_text differs between Serverless and Cloud Hosted.
NARRATIVE_INFERENCE_ID = ".elser-2-elastic"

INDICES = {
    "nba_team_stats": {
        # LOOKUP JOIN (agent_builder find_value_mismatches) only works against
        # lookup-mode indices, and index.mode can't be changed after creation.
        "settings": {"index.mode": "lookup"},
        "mappings": {
            "properties": {
                "team_id": {"type": "keyword"},
                "team": {"type": "keyword"},
                "team_abbreviation": {"type": "keyword"},
                "season": {"type": "keyword"},
                "games_played": {"type": "integer"},
                "wins": {"type": "integer"},
                "losses": {"type": "integer"},
                "points_per_game": {"type": "float"},
                "points_allowed_per_game": {"type": "float"},
                "net_rating": {"type": "float"},
                "home_win_pct": {"type": "float"},
                "away_win_pct": {"type": "float"},
                "last_10_wins": {"type": "integer"},
                "last_10_losses": {"type": "integer"},
                "last_updated": {"type": "date"},
                "narrative": {
                    "type": "semantic_text",
                    "inference_id": NARRATIVE_INFERENCE_ID,
                },
            }
        },
    },
    "nba_games": {
        "mappings": {
            "properties": {
                "game_id": {"type": "keyword"},
                "date": {"type": "date"},
                "season": {"type": "keyword"},
                "home_team": {"type": "keyword"},
                "away_team": {"type": "keyword"},
                "home_score": {"type": "integer"},
                "away_score": {"type": "integer"},
                "status": {"type": "keyword"},
                "winner": {"type": "keyword"},
                "neutral_site": {"type": "boolean"},
            }
        },
    },
    "nba_odds": {
        "mappings": {
            "properties": {
                "game_id": {"type": "keyword"},
                "date": {"type": "date"},
                "home_team": {"type": "keyword"},
                "away_team": {"type": "keyword"},
                "bookmaker": {"type": "keyword"},
                "market": {"type": "keyword"},
                "team": {"type": "keyword"},
                "odds_decimal": {"type": "float"},
                "implied_probability": {"type": "float"},
                "fetched_at": {"type": "date"},
            }
        },
    },
}


def ensure_index(es: Elasticsearch, alias: str) -> None:
    """Create `<alias>_<VERSION>` with its alias if the alias doesn't exist.

    If it already exists, push the current mapping so newly added fields are
    picked up. Adding fields is allowed in place; changing an existing field's
    type fails here and needs a new VERSION + alias swap instead.
    """
    if es.indices.exists_alias(name=alias):
        es.indices.put_mapping(index=alias, properties=INDICES[alias]["mappings"]["properties"])
        return
    if es.indices.exists(index=alias):
        raise RuntimeError(
            f"'{alias}' exists as a concrete index (probably dynamically mapped "
            f"by an old ingest run). Delete it in Dev Tools (DELETE {alias}) "
            f"and re-run so it can be recreated as {alias}_{VERSION} + alias."
        )
    spec = INDICES[alias]
    es.indices.create(
        index=f"{alias}_{VERSION}",
        settings=spec.get("settings"),
        mappings=spec["mappings"],
        aliases={alias: {"is_write_index": True}},
    )
    print(f"Created index '{alias}_{VERSION}' with alias '{alias}'")


def reset_index(es: Elasticsearch, alias: str) -> None:
    """Ensure the index exists and remove all its documents, keeping the mapping."""
    ensure_index(es, alias)
    es.delete_by_query(
        index=alias, query={"match_all": {}}, refresh=True, conflicts="proceed"
    )


def main():
    from es_client import get_client

    es = get_client()
    for alias in INDICES:
        ensure_index(es, alias)
    print("All indices ready.")


if __name__ == "__main__":
    main()
