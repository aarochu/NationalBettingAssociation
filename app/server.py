"""NationalBettingAssociation local web app.

FastAPI serves the frontend in app/static and a small JSON API over the live
Elasticsearch indices. Every number on the page comes from an ES|QL query in
this file, and each response carries the query text so the page's "Under the
hood" section can show exactly what ran.

The chat panel proxies Kibana's Agent Builder converse API. The API key stays
on this server; the browser never sees it.

Run from the repo root:
    ./app/run.sh
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from statistics import mean

import httpx
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
load_dotenv(ROOT / ".env")

# The model math lives in one place. reference_model.py is what the agent's
# arithmetic gets checked against, so the page uses the same functions.
sys.path.insert(0, str(ROOT / "scripts"))
from reference_model import (  # noqa: E402
    HOME_COURT_BONUS,
    LOGISTIC_SCALE,
    MISMATCH_THRESHOLD,
    NET_RATING_WEIGHT,
    RECENT_FORM_WEIGHT,
    devig,
    win_probability,
)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


ES_ENDPOINT = _require("ELASTIC_ENDPOINT")
API_KEY = _require("ELASTIC_API_KEY")
KIBANA_URL = os.environ.get("KIBANA_URL", "").strip().rstrip("/")
AGENT_ID = os.environ.get("AGENT_ID", "nba_value_finder")

es = Elasticsearch(ES_ENDPOINT, api_key=API_KEY, request_timeout=60)
app = FastAPI(title="NationalBettingAssociation", docs_url="/api/docs")


# --- Queries -----------------------------------------------------------------
# Same form guard and weights as esql/value_mismatches.esql. The weights are
# interpolated from reference_model.py so tuning one constant there moves the
# page too (the .esql files and agent instructions still need a hand edit).

FORM = (
    "| EVAL last_10_games = last_10_wins + last_10_losses "
    "| EVAL last_10_win_pct = CASE(last_10_games == 0, 0.5, "
    "TO_DOUBLE(last_10_wins) / TO_DOUBLE(last_10_games)) "
)
SCORE = f"(net_rating * {NET_RATING_WEIGHT}) + (last_10_win_pct * {RECENT_FORM_WEIGHT})"

Q_MARKETS = (
    'FROM nba_odds | WHERE market == "h2h" '
    "| LOOKUP JOIN nba_team_stats ON team "
    "| WHERE net_rating IS NOT NULL "
    + FORM
    + "| EVAL is_home = team == home_team "
    f"| EVAL raw_score = ROUND({SCORE} + CASE(is_home, {HOME_COURT_BONUS}, 0.0), 2) "
    "| KEEP game_id, date, home_team, away_team, team, team_abbreviation, is_home, "
    "bookmaker, odds_decimal, implied_probability, wins, losses, net_rating, "
    "last_10_wins, last_10_losses, last_10_win_pct, raw_score "
    "| SORT date ASC, game_id ASC | LIMIT 5000"
)

Q_TEAMS = (
    "FROM nba_team_stats "
    + FORM
    + f"| EVAL raw_score = ROUND({SCORE}, 2) "
    "| KEEP team, team_abbreviation, wins, losses, net_rating, points_per_game, "
    "points_allowed_per_game, home_win_pct, away_win_pct, last_10_wins, "
    "last_10_losses, last_10_win_pct, raw_score, narrative "
    "| SORT raw_score DESC | LIMIT 30"
)

Q_CONTEXT = (
    "FROM nba_team_stats | STATS teams = COUNT(*), "
    "avg_net_rating = ROUND(AVG(net_rating), 2), "
    "best_net_rating = ROUND(MAX(net_rating), 2), "
    "worst_net_rating = ROUND(MIN(net_rating), 2), "
    "avg_points = ROUND(AVG(points_per_game), 1), "
    "avg_points_allowed = ROUND(AVG(points_allowed_per_game), 1)"
)

Q_HOME_EDGE = (
    "FROM nba_team_stats | STATS avg_home_win_pct = ROUND(AVG(home_win_pct), 3), "
    "avg_away_win_pct = ROUND(AVG(away_win_pct), 3) "
    "| EVAL home_court_edge = ROUND(avg_home_win_pct - avg_away_win_pct, 3)"
)

Q_TIERS = (
    'FROM nba_team_stats | EVAL tier = CASE(net_rating >= 5.0, "1. contender", '
    'net_rating >= 0.0, "2. above .500", net_rating >= -5.0, "3. below .500", '
    '"4. rebuilding") '
    "| STATS teams = COUNT(*), avg_net_rating = ROUND(AVG(net_rating), 2) BY tier "
    "| SORT tier ASC"
)

Q_ODDS = (
    'FROM nba_odds | WHERE market == "h2h" '
    "| STATS games = COUNT_DISTINCT(game_id), books = COUNT_DISTINCT(bookmaker), "
    "prices = COUNT(*), latest_fetch = MAX(fetched_at), "
    "first_game = MIN(date), last_game = MAX(date)"
)

Q_SEARCH = (
    "FROM nba_team_stats METADATA _score "
    "| WHERE MATCH(narrative, ?description) "
    "| KEEP team, team_abbreviation, wins, losses, net_rating, last_10_wins, "
    "last_10_losses, narrative, _score "
    "| SORT _score DESC | LIMIT 8"
)


def run_esql(query: str, params: list | None = None) -> tuple[list[dict], int]:
    started = time.perf_counter()
    kwargs = {"query": query, "format": "json"}
    if params:
        kwargs["params"] = params
    try:
        body = es.esql.query(**kwargs).body
    except Exception as exc:  # surface the ES error text to the page
        raise HTTPException(status_code=502, detail=f"Elasticsearch query failed: {exc}") from exc
    columns = [c["name"] for c in body["columns"]]
    rows = [dict(zip(columns, values)) for values in body["values"]]
    return rows, round((time.perf_counter() - started) * 1000)


def _round(value, digits: int = 4):
    return None if value is None else round(float(value), digits)


# --- Market data ---------------------------------------------------------------


def _team(row: dict) -> dict:
    return {
        "team": row["team"],
        "abbr": row.get("team_abbreviation") or row["team"][:3].upper(),
        "record": f"{row['wins']}-{row['losses']}",
        "last_10": f"{row['last_10_wins']}-{row['last_10_losses']}",
        "net_rating": _round(row["net_rating"], 2),
        "last_10_win_pct": _round(row["last_10_win_pct"], 3),
        "raw_score": row["raw_score"],
        "is_home": bool(row["is_home"]),
    }


@app.get("/api/markets")
def markets():
    """Every priced game: model probability, de-vigged market, and the gap."""
    rows, took = run_esql(Q_MARKETS)

    games: dict[str, dict] = {}
    for row in rows:
        game = games.setdefault(
            row["game_id"],
            {
                "game_id": row["game_id"],
                "date": row["date"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "teams": {},
                "prices": {},
            },
        )
        game["teams"].setdefault(row["team"], _team(row))
        game["prices"].setdefault(row["bookmaker"], {})[row["team"]] = (
            row["odds_decimal"],
            row["implied_probability"],
        )

    out, skipped = [], []
    for game in games.values():
        home = game["teams"].get(game["home_team"])
        away = game["teams"].get(game["away_team"])

        # De-vig each book on its own pair of prices, then average the books.
        books = []
        for name, sides in sorted(game["prices"].items()):
            if game["home_team"] not in sides or game["away_team"] not in sides:
                continue
            home_odds, home_implied = sides[game["home_team"]]
            away_odds, away_implied = sides[game["away_team"]]
            home_market, away_market = devig(home_implied, away_implied)
            books.append(
                {
                    "bookmaker": name,
                    "home_odds": _round(home_odds, 2),
                    "away_odds": _round(away_odds, 2),
                    "home_market": _round(home_market),
                    "away_market": _round(away_market),
                }
            )

        # A pairwise probability needs both teams' stats and at least one book
        # that priced both sides. Skip rather than guess, same as the agent.
        if not home or not away or not books:
            skipped.append(game["game_id"])
            continue

        p_home = win_probability(home["raw_score"], away["raw_score"])
        m_home = mean(b["home_market"] for b in books)
        for side, model, market, odds_key in (
            (home, p_home, m_home, "home_odds"),
            (away, 1 - p_home, 1 - m_home, "away_odds"),
        ):
            side.update(
                model=_round(model),
                market=_round(market),
                delta=_round(model - market),
                best_odds=max(b[odds_key] for b in books),
            )

        gap = abs(p_home - m_home)
        out.append(
            {
                "game_id": game["game_id"],
                "date": game["date"],
                "home": home,
                "away": away,
                "books": books,
                "edge": "home" if p_home >= m_home else "away",
                "gap": _round(gap),
                "flagged": gap >= MISMATCH_THRESHOLD,
            }
        )

    return {
        "games": out,
        "skipped": skipped,
        "rows": len(rows),
        "query": Q_MARKETS,
        "took_ms": took,
        "model": {
            "net_rating_weight": NET_RATING_WEIGHT,
            "recent_form_weight": RECENT_FORM_WEIGHT,
            "home_court_bonus": HOME_COURT_BONUS,
            "logistic_scale": LOGISTIC_SCALE,
            "threshold": MISMATCH_THRESHOLD,
        },
    }


@app.get("/api/teams")
def teams():
    rows, took = run_esql(Q_TEAMS)
    return {"teams": rows, "query": Q_TEAMS, "took_ms": took}


@app.get("/api/league")
def league():
    out = {}
    for key, query in (
        ("context", Q_CONTEXT),
        ("home_edge", Q_HOME_EDGE),
        ("tiers", Q_TIERS),
        ("odds", Q_ODDS),
    ):
        rows, took = run_esql(query)
        out[key] = {"rows": rows, "query": query, "took_ms": took}
    return out


@app.get("/api/search")
def search(q: str = Query(..., min_length=2, max_length=200)):
    """Semantic search over team narratives. The text goes in as a bound param."""
    rows, took = run_esql(Q_SEARCH, params=[{"description": q}])
    return {"q": q, "results": rows, "query": Q_SEARCH, "took_ms": took}


# --- Health ----------------------------------------------------------------------


def _kibana_headers() -> dict:
    return {
        "Authorization": f"ApiKey {API_KEY}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }


@app.get("/api/health")
def health():
    result = {
        "agent_id": AGENT_ID,
        "elasticsearch": {"ok": False},
        "kibana": {"ok": False, "configured": bool(KIBANA_URL)},
    }
    try:
        info = es.info()
        counts = {i: es.count(index=i)["count"] for i in ("nba_team_stats", "nba_games", "nba_odds")}
        result["elasticsearch"] = {"ok": True, "version": info["version"]["number"], "counts": counts}
    except Exception as exc:
        result["elasticsearch"]["error"] = str(exc)[:300]

    if KIBANA_URL:
        try:
            with httpx.Client(timeout=15, headers=_kibana_headers()) as client:
                status = client.get(f"{KIBANA_URL}/api/status")
                agent = client.get(f"{KIBANA_URL}/api/agent_builder/agents/{AGENT_ID}")
            result["kibana"].update(
                ok=status.status_code == 200,
                version=status.json().get("version", {}).get("number") if status.status_code == 200 else None,
                agent_registered=agent.status_code == 200,
            )
        except Exception as exc:
            result["kibana"]["error"] = str(exc)[:300]
    return result


# --- Chat: Kibana Agent Builder wrapper -------------------------------------------


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


def _walk(node):
    stack = [node]
    while stack:
        item = stack.pop()
        yield item
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _row_count(results) -> int | None:
    counts = [len(n["values"]) for n in _walk(results) if isinstance(n, dict) and isinstance(n.get("values"), list)]
    return sum(counts) if counts else None


def _query_in(results) -> str | None:
    for node in _walk(results):
        if isinstance(node, dict):
            for key in ("esql", "query"):
                if isinstance(node.get(key), str) and "FROM" in node[key]:
                    return node[key]
    return None


def _steps(raw_steps) -> list[dict]:
    """Flatten Agent Builder's step list into what the chat trace renders."""
    steps = []
    for step in raw_steps or []:
        if not isinstance(step, dict):
            continue
        if step.get("tool_id"):
            results = step.get("results") or []
            preview = json.dumps(results, default=str)
            steps.append(
                {
                    "kind": "tool",
                    "tool_id": step["tool_id"],
                    "params": step.get("params") or {},
                    "rows": _row_count(results),
                    "query": _query_in(results),
                    "preview": preview if len(preview) <= 3000 else preview[:3000] + " ...",
                }
            )
        elif step.get("reasoning"):
            steps.append({"kind": "reasoning", "text": str(step["reasoning"])[:1500]})
    return steps


@app.post("/api/chat")
async def chat(body: ChatIn):
    if not KIBANA_URL:
        raise HTTPException(503, "KIBANA_URL isn't set in .env, so there's no agent to talk to.")

    payload = {"agent_id": AGENT_ID, "input": body.message}
    if body.conversation_id:
        payload["conversation_id"] = body.conversation_id

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=240, headers=_kibana_headers()) as client:
            resp = await client.post(f"{KIBANA_URL}/api/agent_builder/converse", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Couldn't reach Kibana: {exc}") from exc

    if resp.status_code >= 400:
        detail = resp.text[:500]
        if resp.status_code == 404 and "agent" in detail.lower():
            detail += " (run: .venv/bin/python scripts/setup_agent.py)"
        raise HTTPException(502, f"Kibana returned {resp.status_code}: {detail}")

    data = resp.json()
    return {
        "agent_id": AGENT_ID,
        "conversation_id": data.get("conversation_id"),
        "message": (data.get("response") or {}).get("message") or "",
        "steps": _steps(data.get("steps")),
        "took_ms": round((time.perf_counter() - started) * 1000),
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/api/chat/stream")
async def chat_stream(body: ChatIn):
    """The same agent call as /api/chat, relayed as server-sent events.

    A full answer can take minutes, so the page needs to show tool calls as
    they happen. Kibana's converse/async endpoint streams its own events; this
    passes along the ones the chat panel draws, under shorter names:
    conversation, reasoning, tool_call, tool_result, chunk, error, done.
    """
    if not KIBANA_URL:
        raise HTTPException(503, "KIBANA_URL isn't set in .env, so there's no agent to talk to.")

    payload = {"agent_id": AGENT_ID, "input": body.message}
    if body.conversation_id:
        payload["conversation_id"] = body.conversation_id

    async def events():
        started = time.perf_counter()
        conversation_id = body.conversation_id
        message = ""
        usage = {}
        yield _sse("reasoning", {"text": "Sent to Agent Builder"})
        try:
            timeout = httpx.Timeout(600, connect=15)
            async with httpx.AsyncClient(timeout=timeout, headers=_kibana_headers()) as client:
                url = f"{KIBANA_URL}/api/agent_builder/converse/async"
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        detail = (await resp.aread()).decode(errors="replace")[:500]
                        yield _sse("error", {"detail": f"Kibana returned {resp.status_code}: {detail}"})
                        return
                    event = None
                    async for line in resp.aiter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            continue
                        try:
                            data = json.loads(line[5:].strip()).get("data") or {}
                        except (json.JSONDecodeError, AttributeError):
                            continue

                        if event in ("conversation_id_set", "conversation_created"):
                            if data.get("conversation_id") and data["conversation_id"] != conversation_id:
                                conversation_id = data["conversation_id"]
                                yield _sse("conversation", {"conversation_id": conversation_id})
                        elif event == "reasoning" and data.get("reasoning"):
                            yield _sse("reasoning", {"text": str(data["reasoning"])[:300]})
                        elif event == "tool_call":
                            yield _sse("tool_call", {
                                "call_id": data.get("tool_call_id"),
                                "tool_id": data.get("tool_id"),
                                "params": data.get("params") or {},
                            })
                        elif event == "tool_result":
                            results = data.get("results") or []
                            preview = json.dumps(results, default=str)
                            yield _sse("tool_result", {
                                "call_id": data.get("tool_call_id"),
                                "tool_id": data.get("tool_id"),
                                "rows": _row_count(results),
                                "query": _query_in(results),
                                "preview": preview if len(preview) <= 3000 else preview[:3000] + " ...",
                            })
                        elif event == "message_chunk" and data.get("text_chunk"):
                            yield _sse("chunk", {"text": data["text_chunk"]})
                        elif event == "message_complete":
                            message = data.get("message_content") or message
                        elif event == "round_complete":
                            rnd = data.get("round") or {}
                            message = (rnd.get("response") or {}).get("message") or message
                            usage = rnd.get("model_usage") or {}
                        elif event == "error" or "error" in data:
                            err = data.get("error") or data
                            detail = err.get("message") if isinstance(err, dict) else str(err)
                            yield _sse("error", {"detail": str(detail)[:500]})
                            return
        except httpx.HTTPError as exc:
            yield _sse("error", {"detail": f"Lost the connection to Kibana: {exc!r}"})
            return

        yield _sse("done", {
            "agent_id": AGENT_ID,
            "conversation_id": conversation_id,
            "message": message,
            "model": usage.get("model"),
            "llm_calls": usage.get("llm_calls"),
            "took_ms": round((time.perf_counter() - started) * 1000),
        })

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Frontend ----------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
