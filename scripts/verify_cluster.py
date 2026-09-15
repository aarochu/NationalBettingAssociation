#!/usr/bin/env python3
"""
Run every cluster-dependent item in Raymond's todo against a live Elastic
endpoint, and check the results against scripts/reference_model.py.

Nothing in the repo depends on this; it's a test harness. Stdlib only, so
there's nothing to install.

    export ES_ENDPOINT="https://<your-deployment>.us-east4.gcp.elastic-cloud.com"
    export ES_API_KEY="<base64 api key>"
    python3 scripts/verify_cluster.py

Add --seed to create the three indices and load the sample docs first.
Safe to re-run; seeding twice just duplicates sample docs, so only seed once.

What it checks, in order:
  1. The endpoint answers and the key authenticates.
  2. All three indices exist and have documents in them.
  3. esql/win_probability.esql parses and returns a ranked list.
  4. matchup_comparison query B returns both sides of the sample game, and
     reports whether the stored odds are de-vigged.
  5. Whether LOOKUP JOIN works, and if not, whether the lookup-mode mirror
     fixes it -- this is the risky one flagged in agent_builder/setup.md.
  6. The full value-mismatch query, with its numbers diffed against the
     reference model. This is the real test: it catches a formula that runs
     without erroring but computes the wrong thing.
  7. Semantic search over the narrative field, run twice with opposite
     meanings. Ranking by _score has to actually change between the two runs
     -- if it doesn't, MATCH() is behaving like a keyword search and the
     embedding isn't being used.

Agent Builder tool registration is NOT covered. Those are Kibana APIs on a
different host than the Elasticsearch endpoint, so paste those blocks from
agent_builder/setup.md by hand.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reference_model import (  # noqa: E402
    LOGISTIC_SCALE,
    MISMATCH_THRESHOLD,
    devig,
    win_probability,
)

ENDPOINT = os.environ.get("ES_ENDPOINT", "").rstrip("/")
API_KEY = os.environ.get("ES_API_KEY", "")

SAMPLE_GAME = "2026-09-20-BOS-NYK"

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def record(status, label, detail=""):
    results.append((status, label, detail))
    icon = {PASS: "  ok ", FAIL: "FAIL ", WARN: "warn "}[status]
    print(f"{icon} {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"        {line}")


def request(method, path, body=None):
    """One HTTP call to Elasticsearch. Returns (status_code, parsed_body)."""
    url = f"{ENDPOINT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"ApiKey {API_KEY}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:500]}
    except Exception as e:
        return 0, {"error": str(e)}


def esql(query):
    """Run an ES|QL query, returning (ok, rows_as_dicts_or_error_string)."""
    status, body = request("POST", "/_query?format=json", {"query": query})
    if status != 200:
        err = body.get("error", body)
        if isinstance(err, dict):
            err = err.get("reason") or json.dumps(err)[:300]
        return False, str(err)
    cols = [c["name"] for c in body.get("columns", [])]
    return True, [dict(zip(cols, row)) for row in body.get("values", [])]


# --- query bodies, kept identical to the committed .esql files -------------

FORM_GUARD = (
    "| EVAL last_10_games = last_10_wins + last_10_losses "
    "| EVAL last_10_win_pct = CASE(last_10_games == 0, 0.5, "
    "TO_DOUBLE(last_10_wins) / TO_DOUBLE(last_10_games)) "
)

Q_WIN_PROBABILITY = (
    "FROM nba_team_stats " + FORM_GUARD +
    "| EVAL raw_score = ROUND((net_rating * 0.5) + (last_10_win_pct * 30), 2) "
    "| KEEP team, team_abbreviation, net_rating, last_10_win_pct, raw_score "
    "| SORT raw_score DESC"
)

Q_ODDS = (
    f'FROM nba_odds | WHERE game_id == "{SAMPLE_GAME}" '
    "| KEEP game_id, home_team, away_team, team, odds_decimal, implied_probability "
    "| SORT team"
)


def q_mismatches(stats_index):
    return (
        'FROM nba_odds | WHERE market == "h2h" '
        f"| LOOKUP JOIN {stats_index} ON team "
        "| WHERE net_rating IS NOT NULL " + FORM_GUARD +
        "| EVAL is_home = team == home_team "
        "| EVAL raw_score = ROUND((net_rating * 0.5) + (last_10_win_pct * 30) "
        "+ CASE(is_home, 5.0, 0.0), 2) "
        "| KEEP game_id, home_team, away_team, team, is_home, "
        "implied_probability, net_rating, last_10_win_pct, raw_score "
        "| SORT game_id ASC, raw_score DESC"
    )


Q_SEMANTIC = (
    "FROM nba_team_stats METADATA _score "
    '| WHERE MATCH(narrative, "{desc}") '
    "| KEEP team, narrative, _score "
    "| SORT _score DESC | LIMIT 10"
)

# Two descriptions that share vocabulary but mean opposite things. A working
# embedding ranks different teams first for each; a keyword fallback returns
# roughly the same order both times.
SEMANTIC_POSITIVE = "lockdown defense and playing hot right now"
SEMANTIC_NEGATIVE = "struggling badly and losing at home lately"

LOOKUP_INDEX = "nba_team_stats_lookup"


def create_lookup_mirror():
    """The fix from agent_builder/setup.md, applied automatically."""
    request("DELETE", f"/{LOOKUP_INDEX}")
    status, body = request("PUT", f"/{LOOKUP_INDEX}", {
        "settings": {"index.mode": "lookup"},
        "mappings": {"properties": {
            "team": {"type": "keyword"},
            "team_abbreviation": {"type": "keyword"},
            "net_rating": {"type": "float"},
            "last_10_wins": {"type": "integer"},
            "last_10_losses": {"type": "integer"},
            "wins": {"type": "integer"},
            "losses": {"type": "integer"},
        }},
    })
    if status >= 300:
        return False, body
    status, body = request("POST", "/_reindex?refresh=true", {
        "source": {"index": "nba_team_stats"},
        "dest": {"index": LOOKUP_INDEX},
    })
    return status < 300, body


# --- checks ----------------------------------------------------------------

def check_connection():
    status, body = request("GET", "/")
    if status == 200:
        v = body.get("version", {}).get("number", "unknown")
        record(PASS, "Endpoint reachable and key accepted", f"version {v}")
        return True
    if status in (401, 403):
        record(FAIL, "Authentication rejected",
               "Check ES_API_KEY. It should be the base64 'id:key' form, "
               "passed as 'Authorization: ApiKey <value>'.")
    else:
        record(FAIL, f"Could not reach endpoint (status {status})", body)
    return False


def check_indices():
    ok = True
    for idx in ("nba_team_stats", "nba_games", "nba_odds"):
        status, body = request("GET", f"/{idx}/_count")
        if status != 200:
            record(FAIL, f"Index {idx} missing",
                   "Run mappings/*.json in Dev Tools, or pass --seed.")
            ok = False
            continue
        count = body.get("count", 0)
        if count == 0:
            record(WARN, f"Index {idx} exists but is empty",
                   "Load mappings/sample_docs.md, or pass --seed.")
        else:
            record(PASS, f"Index {idx} has {count} document(s)")
    return ok


def check_win_probability():
    ok, rows = esql(Q_WIN_PROBABILITY)
    if not ok:
        record(FAIL, "win_probability.esql failed", rows)
        return
    if not rows:
        record(WARN, "win_probability.esql ran but returned no rows")
        return
    nulls = [r["team"] for r in rows if r.get("raw_score") is None]
    if nulls:
        record(FAIL, "win_probability.esql returned null scores",
               f"divide-by-zero guard not working for: {', '.join(nulls)}")
        return
    top = ", ".join(f"{r['team']} {r['raw_score']}" for r in rows[:3])
    record(PASS, f"win_probability.esql ranked {len(rows)} team(s)", top)


def check_odds():
    ok, rows = esql(Q_ODDS)
    if not ok:
        record(FAIL, "matchup_comparison query B failed", rows)
        return
    if len(rows) < 2:
        record(WARN, f"Sample game {SAMPLE_GAME} has {len(rows)} odds row(s)",
               "Expected 2 (one per team). Cross-game ranking will skip it.")
        return
    total = sum(r["implied_probability"] for r in rows)
    if total > 1.005:
        record(PASS, f"Odds present; book total {total:.3f}",
               f"Not de-vigged (vig {(total - 1) * 100:.1f}pp) -- the agent "
               "must normalize. This is expected for sample data.")
    else:
        record(PASS, f"Odds present; book total {total:.3f}",
               "Already de-vigged at ingest. Agent normalization is a no-op.")


def check_lookup_join():
    """Returns the stats index name that works with LOOKUP JOIN, or None."""
    ok, rows = esql(q_mismatches("nba_team_stats"))
    if ok:
        record(PASS, "LOOKUP JOIN works against nba_team_stats",
               "Expected -- ingest/indices.py creates it in lookup mode. "
               "Use the tool JSON as committed.")
        return "nba_team_stats"

    record(WARN, "LOOKUP JOIN against nba_team_stats failed", rows)
    print("        ingest/indices.py should create this in lookup mode --")
    print("        check for a stale concrete index (DELETE nba_team_stats,")
    print("        then re-run ingest). Trying a temporary mirror meanwhile...")
    built, detail = create_lookup_mirror()
    if not built:
        record(FAIL, "Could not build the lookup-mode mirror", detail)
        record(WARN, "Use the get_all_stats_scores fallback tool",
               "See the LOOKUP JOIN section of agent_builder/setup.md. "
               "Drop find_value_mismatches from the agent's tool list.")
        return None

    ok, rows = esql(q_mismatches(LOOKUP_INDEX))
    if ok:
        record(PASS, f"LOOKUP JOIN works against {LOOKUP_INDEX}",
               "This is a workaround, not the fix: the real problem is that "
               "nba_team_stats isn't in lookup mode, which ingest/indices.py "
               "is supposed to guarantee. Delete the stale index and re-run "
               "ingest rather than shipping the mirror, which goes stale.")
        return LOOKUP_INDEX

    record(FAIL, "Mirror built but LOOKUP JOIN still fails", rows)
    record(WARN, "Use the get_all_stats_scores fallback tool",
           "See the LOOKUP JOIN section of agent_builder/setup.md.")
    return None


def check_numbers(stats_index):
    """The important one: does the cluster compute what the model says?"""
    ok, rows = esql(q_mismatches(stats_index))
    if not ok:
        record(FAIL, "Value-mismatch query failed", rows)
        return

    games = {}
    for r in rows:
        games.setdefault(r["game_id"], []).append(r)

    checked = 0
    for game_id, teams in sorted(games.items()):
        if len(teams) != 2:
            record(WARN, f"{game_id}: {len(teams)} row(s), expected 2",
                   "Skipped -- a pairwise probability needs both sides.")
            continue

        a, b = teams

        required = {"raw_score", "net_rating", "last_10_win_pct",
                    "is_home", "implied_probability"}
        for row in (a, b):
            missing = required - row.keys()
            if missing:
                record(FAIL, f"{game_id}: query result is missing columns",
                       f"absent: {', '.join(sorted(missing))}. The query ran "
                       "but didn't return what the checks expect -- compare "
                       "its KEEP clause against esql/value_mismatches.esql.")
                break
        else:
            pass
        if required - a.keys() or required - b.keys():
            continue

        # The query returns last_10_win_pct rather than the raw win/loss
        # counts, so rebuild the expected score from the pct directly rather
        # than going through raw_score().
        def expect(row):
            return round(
                row["net_rating"] * 0.5
                + row["last_10_win_pct"] * 30
                + (5.0 if row["is_home"] else 0.0), 2)

        drift = [(r["team"], r["raw_score"], expect(r))
                 for r in (a, b)
                 if abs(r["raw_score"] - expect(r)) > 0.011]
        if drift:
            record(FAIL, f"{game_id}: raw_score disagrees with model.md",
                   "\n".join(f"{t}: cluster {got} vs expected {exp}"
                             for t, got, exp in drift))
            continue

        p_a = win_probability(a["raw_score"], b["raw_score"])
        m_a, m_b = devig(a["implied_probability"], b["implied_probability"])
        d_a, d_b = p_a - m_a, (1 - p_a) - m_b

        if abs(d_a + d_b) > 0.001:
            record(FAIL, f"{game_id}: deltas are not mirrors",
                   f"{d_a * 100:+.1f}pp and {d_b * 100:+.1f}pp -- de-vig is wrong.")
            continue

        if p_a > 0.97 or p_a < 0.03:
            record(WARN, f"{game_id}: probability saturated at {p_a * 100:.1f}%",
                   f"Scale divisor {LOGISTIC_SCALE} may be too small for these "
                   "scores. See the tuning table in docs/model.md.")

        flag = "FLAGGED" if abs(d_a) >= MISMATCH_THRESHOLD else "no flag"
        record(PASS, f"{game_id}: numbers check out",
               f"{a['team']} model {p_a * 100:.1f}% vs market {m_a * 100:.1f}% "
               f"({d_a * 100:+.1f}pp, {flag})")
        checked += 1

    if checked:
        record(PASS, f"{checked} game(s) fully verified against reference_model.py")


def check_semantic():
    ok, pos = esql(Q_SEMANTIC.format(desc=SEMANTIC_POSITIVE))
    if not ok:
        if "semantic" in str(pos).lower() or "MATCH" in str(pos):
            record(WARN, "ES|QL MATCH() on semantic_text not supported", pos)
            record(WARN, "Use the Query DSL fallback",
                   "See esql/team_narrative_search.esql, and register "
                   "find_similar_teams as a 'query' type tool instead.")
        else:
            record(FAIL, "Semantic search query failed", pos)
        return
    if not pos:
        record(WARN, "Semantic search returned no rows",
               "Is the narrative field populated? Documents indexed before "
               "the semantic_text mapping was applied are not embedded "
               "retroactively -- reindex them.")
        return

    record(PASS, f"Semantic search returned {len(pos)} team(s)",
           f"top: {pos[0]['team']} (_score {pos[0].get('_score')})")

    ok, neg = esql(Q_SEMANTIC.format(desc=SEMANTIC_NEGATIVE))
    if not ok or not neg:
        record(WARN, "Could not run the inverted-meaning comparison", neg)
        return

    same_order = [r["team"] for r in pos] == [r["team"] for r in neg]
    scores_moved = any(
        abs((a.get("_score") or 0) - (b.get("_score") or 0)) > 0.01
        for a, b in zip(pos, neg))

    if same_order and not scores_moved:
        record(FAIL, "Semantic search is not discriminating by meaning",
               "Opposite descriptions returned the same order AND the same "
               "scores. MATCH() is likely falling back to keyword behaviour. "
               "Check GET nba_team_stats/_mapping shows narrative as "
               "semantic_text, and that docs were indexed after that mapping.")
    elif same_order:
        record(WARN, "Same ranking for opposite descriptions, but scores moved",
               "Plausible with only two sample teams. Re-check once there are "
               "more teams in the index.")
    else:
        record(PASS, "Semantic ranking responds to meaning",
               f"'{SEMANTIC_POSITIVE[:30]}...' -> {pos[0]['team']}; "
               f"'{SEMANTIC_NEGATIVE[:30]}...' -> {neg[0]['team']}")


def check_narrative_vocabulary():
    """The sample narratives are richer than build_narrative() output."""
    ok, rows = esql("FROM nba_team_stats | KEEP team, narrative | LIMIT 50")
    if not ok or not rows:
        return
    blobs = " ".join((r.get("narrative") or "").lower() for r in rows)
    missing = [w for w in ("defense", "shooting", "road") if w not in blobs]
    if missing:
        record(WARN,
               f"Narratives never mention: {', '.join(missing)}",
               "Play-style prompts about those themes have nothing to match. "
               "If this is live data, build_narrative() needs widening -- see "
               "the note flagged for Aaron in docs/todo.md. Until then use a "
               "demo prompt inside the template's vocabulary (overall form, "
               "hot/cold streak, home comfort).")
    else:
        record(PASS, "Narratives cover defense, shooting and road themes")


def seed():
    print("Seeding indices and sample documents...\n")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("nba_team_stats", "nba_games", "nba_odds"):
        path = os.path.join(here, "mappings", f"{name}.json")
        with open(path) as f:
            body = json.loads("".join(
                l for l in f if not l.strip().startswith(("//", "PUT"))))
        request("DELETE", f"/{name}")
        status, resp = request("PUT", f"/{name}", body)
        record(PASS if status < 300 else FAIL, f"Created index {name}",
               "" if status < 300 else resp)

    docs = []
    md = os.path.join(here, "mappings", "sample_docs.md")
    with open(md) as f:
        text = f.read()
    for block in text.split("```")[1::2]:
        lines = block.strip().splitlines()
        if not lines or not lines[0].startswith("POST "):
            continue
        target = lines[0].split()[1]
        if not target.endswith("/_doc"):
            continue
        docs.append((target.split("/")[0], "\n".join(lines[1:])))

    for index, raw in docs:
        status, resp = request("POST", f"/{index}/_doc?refresh=true",
                               json.loads(raw))
        record(PASS if status < 300 else FAIL,
               f"Indexed sample doc into {index}",
               "" if status < 300 else resp)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true",
                    help="Create indices and load sample docs first.")
    args = ap.parse_args()

    if not ENDPOINT or not API_KEY:
        print("Set ES_ENDPOINT and ES_API_KEY first. See the docstring.")
        return 2

    print(f"Verifying {ENDPOINT}\n")
    if not check_connection():
        return 1
    if args.seed:
        seed()
    check_indices()
    check_win_probability()
    check_odds()
    stats_index = check_lookup_join()
    if stats_index:
        check_numbers(stats_index)
    check_semantic()
    check_narrative_vocabulary()

    failures = sum(1 for s, _, _ in results if s == FAIL)
    warnings = sum(1 for s, _, _ in results if s == WARN)
    print(f"\n{len(results)} check(s): {failures} failed, {warnings} warning(s)")
    if failures:
        print("\nFailed:")
        for s, label, _ in results:
            if s == FAIL:
                print(f"  - {label}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
