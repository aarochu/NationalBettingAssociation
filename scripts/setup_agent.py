#!/usr/bin/env python3
"""
Register the Agent Builder tools and agent defined in agent_builder/setup.md.

setup.md stays the source of truth. This script pulls the JSON blocks out of
it and sends them to Kibana, so nobody has to paste them into Dev Tools by
hand and the registered tools can't drift from the docs.

    python3 scripts/setup_agent.py             # create or update everything
    python3 scripts/setup_agent.py --check     # then run each tool once
    python3 scripts/setup_agent.py --ask "Which games have the biggest gap?"

Reads ELASTIC_API_KEY and KIBANA_URL from .env. Stdlib only.

The Dev Tools blocks and the HTTP API disagree in two places, and this script
papers over both:
  * The blocks say `PUT .../tools/<id>`, but PUT only updates. Creating a
    tool is `POST .../tools` with the id in the body.
  * The blocks declare ES|QL params as "keyword"; the API wants "string".

Kibana 9.5 marks every declared param as required, so get_market_odds needs
both `team` and `game_id` on every call. --check passes an empty game_id to
confirm that still returns rows.

Only tools the agent lists get registered, so the get_all_stats_scores
fallback in setup.md stays out of Kibana unless someone adds it to the agent.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP_MD = ROOT / "agent_builder" / "setup.md"

BLOCK = re.compile(
    r"```json\s*\n\s*PUT kbn:/api/agent_builder/(tools|agents)/([\w.-]+)\s*\n(.*?)\n```",
    re.S,
)
PARAM_TYPES = {"keyword": "string", "text": "string"}

# Arguments used by --check. Tools that take no params get {}.
CHECK_PARAMS = {
    "get_market_odds": {"team": "Boston Celtics", "game_id": ""},
    "get_stats_prediction": {"team": "Boston Celtics"},
    "find_similar_teams": {"description": "lockdown defense on a hot streak"},
}


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class Kibana:
    def __init__(self, url, api_key):
        self.url = url.rstrip("/")
        self.api_key = api_key

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", f"ApiKey {self.api_key}")
        req.add_header("kbn-xsrf", "true")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"message": raw[:500]}
        except urllib.error.URLError as exc:
            return 0, {"message": str(exc.reason)}


def error_text(body):
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or json.dumps(body)[:300])
    return str(body)[:300]


def parse_setup():
    tools, agents = {}, {}
    for kind, item_id, raw in BLOCK.findall(SETUP_MD.read_text()):
        try:
            spec = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.exit(f"setup.md: the {kind[:-1]} block for {item_id} isn't valid JSON ({exc})")
        (tools if kind == "tools" else agents)[item_id] = spec
    return tools, agents


def tool_payload(tool_id, spec):
    config = dict(spec["configuration"])
    params = {}
    for name, param in (config.get("params") or {}).items():
        param = dict(param)
        param["type"] = PARAM_TYPES.get(param.get("type"), param.get("type"))
        params[name] = param
    config["params"] = params
    return {
        "id": tool_id,
        "type": spec["type"],
        "description": spec["description"],
        "configuration": config,
    }


def agent_payload(agent_id, spec):
    return {
        "id": agent_id,
        "name": spec["name"],
        "description": spec["description"],
        "configuration": {
            "instructions": spec["instructions"],
            "tools": [{"tool_ids": spec["tools"]}],
        },
    }


def upsert(kb, kind, payload):
    base = f"/api/agent_builder/{kind}"
    item_id = payload["id"]
    status, _ = kb.call("GET", f"{base}/{item_id}")
    if status == 200:
        body = {k: v for k, v in payload.items() if k not in ("id", "type")}
        status, resp = kb.call("PUT", f"{base}/{item_id}", body)
        verb = "updated"
    else:
        status, resp = kb.call("POST", base, payload)
        verb = "created"
    ok = 200 <= status < 300
    label = verb if ok else f"failed ({status}): {error_text(resp)}"
    print(f"  {'ok  ' if ok else 'FAIL'} {kind[:-1]} {item_id} {label}")
    return ok


def count_rows(node):
    """Total rows across any tabular payloads nested in a tool result."""
    total, stack = 0, [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get("values"), list):
                total += len(item["values"])
            stack.extend(v for k, v in item.items() if k != "values")
        elif isinstance(item, list):
            stack.extend(item)
    return total


def check_tools(kb, tool_ids):
    print("\nRunning each tool once:")
    all_ok = True
    for tool_id in tool_ids:
        status, resp = kb.call(
            "POST",
            "/api/agent_builder/tools/_execute",
            {"tool_id": tool_id, "tool_params": CHECK_PARAMS.get(tool_id, {})},
        )
        results = resp.get("results") if isinstance(resp, dict) else None
        errors = [r for r in results or [] if r.get("type") == "error"]
        if status != 200 or errors:
            all_ok = False
            detail = error_text(errors[0].get("data", {})) if errors else error_text(resp)
            print(f"  FAIL {tool_id}: {detail}")
        else:
            print(f"  ok   {tool_id}: {count_rows(results)} row(s)")
    return all_ok


def ask(kb, agent_id, question):
    print(f"\nAsking {agent_id}: {question}")
    status, resp = kb.call(
        "POST", "/api/agent_builder/converse", {"agent_id": agent_id, "input": question}
    )
    if status != 200:
        print(f"  FAIL ({status}) {error_text(resp)}")
        return False
    tools = [s.get("tool_id") for s in resp.get("steps", []) if s.get("tool_id")]
    print(f"  tools called: {', '.join(tools) or 'none'}\n")
    print((resp.get("response") or {}).get("message") or json.dumps(resp)[:1500])
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="run each tool once after registering")
    ap.add_argument("--ask", metavar="QUESTION", help="send one question to the agent")
    args = ap.parse_args()

    load_env()
    kibana_url = os.environ.get("KIBANA_URL", "")
    api_key = os.environ.get("ELASTIC_API_KEY", "")
    if not kibana_url or not api_key:
        print("Set KIBANA_URL and ELASTIC_API_KEY in .env first.")
        return 2

    kb = Kibana(kibana_url, api_key)
    tools, agents = parse_setup()
    if not agents:
        print(f"No agent block found in {SETUP_MD.relative_to(ROOT)}.")
        return 1

    ok = True
    for agent_id, spec in agents.items():
        missing = [t for t in spec["tools"] if t not in tools]
        if missing:
            print(f"Agent {agent_id} lists tools with no block in setup.md: {', '.join(missing)}")
            return 1

        print(f"Registering {len(spec['tools'])} tool(s) and agent {agent_id} in {kb.url}")
        for tool_id in spec["tools"]:
            ok &= upsert(kb, "tools", tool_payload(tool_id, tools[tool_id]))
        ok &= upsert(kb, "agents", agent_payload(agent_id, spec))

        if args.check and ok:
            ok &= check_tools(kb, spec["tools"])
        if args.ask and ok:
            ok &= ask(kb, agent_id, args.ask)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
