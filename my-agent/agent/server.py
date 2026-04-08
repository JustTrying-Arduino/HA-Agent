"""aiohttp web server: dashboard + JSON API endpoints."""

import asyncio
import json
import logging
from pathlib import Path

from aiohttp import web

from agent.config import cfg
from agent import db

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Approximate cost per 1M tokens (USD) — adjust as needed
MODEL_COSTS = {
    "gpt-4.1": {"input": 2.0, "cached": 0.5, "output": 8.0},
    "gpt-4.1-mini": {"input": 0.4, "cached": 0.1, "output": 1.6},
    "gpt-4.1-nano": {"input": 0.1, "cached": 0.025, "output": 0.4},
    "gpt-4o": {"input": 2.5, "cached": 1.25, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "cached": 0.075, "output": 0.6},
}
DEFAULT_COST = {"input": 3.0, "cached": 1.5, "output": 10.0}


async def handle_index(request: web.Request) -> web.Response:
    index_path = STATIC_DIR / "index.html"
    return web.FileResponse(index_path)


async def handle_stats(request: web.Request) -> web.Response:
    period = request.query.get("period", "day")

    if period == "day":
        group_expr = "date(timestamp)"
    elif period == "week":
        group_expr = "strftime('%Y-W%W', timestamp)"
    else:
        group_expr = "strftime('%Y-%m', timestamp)"

    rows = db.fetchall(
        f"SELECT {group_expr} as period, model, "
        "SUM(input_tokens) as input_tokens, "
        "SUM(output_tokens) as output_tokens, "
        "SUM(cached_tokens) as cached_tokens "
        "FROM token_usage "
        f"GROUP BY {group_expr}, model "
        "ORDER BY period DESC "
        "LIMIT 100"
    )

    data = []
    for r in rows:
        model = r["model"]
        costs = MODEL_COSTS.get(model, DEFAULT_COST)
        input_t = r["input_tokens"]
        output_t = r["output_tokens"]
        cached_t = r["cached_tokens"]
        # Cost: non-cached input at full price, cached at cached price, output at output price
        non_cached_input = input_t - cached_t
        estimated_cost = (
            non_cached_input / 1_000_000 * costs["input"]
            + cached_t / 1_000_000 * costs["cached"]
            + output_t / 1_000_000 * costs["output"]
        )
        data.append({
            "period": r["period"],
            "model": model,
            "input_tokens": input_t,
            "output_tokens": output_t,
            "cached_tokens": cached_t,
            "estimated_cost": round(estimated_cost, 4),
        })

    return web.json_response({"data": data})


async def handle_messages(request: web.Request) -> web.Response:
    chat_id = request.query.get("chat_id")
    limit = int(request.query.get("limit", "50"))

    if chat_id:
        rows = db.fetchall(
            "SELECT id, chat_id, role, content, timestamp, archived "
            "FROM messages WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
            (int(chat_id), limit),
        )
    else:
        rows = db.fetchall(
            "SELECT id, chat_id, role, content, timestamp, archived "
            "FROM messages ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    messages = [dict(r) for r in rows]
    messages.reverse()

    # Attach tool calls to messages
    if messages:
        msg_ids = [m["id"] for m in messages]
        # Get tool calls in the time range of these messages
        if len(messages) >= 2:
            min_ts = messages[0]["timestamp"]
            max_ts = messages[-1]["timestamp"]
            tool_rows = db.fetchall(
                "SELECT * FROM tool_calls "
                "WHERE chat_id = ? AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp",
                (messages[0]["chat_id"], min_ts, max_ts),
            )
            tool_calls = [dict(r) for r in tool_rows]
        else:
            tool_calls = []

        return web.json_response({"messages": messages, "tool_calls": tool_calls})

    return web.json_response({"messages": [], "tool_calls": []})


async def handle_tool_calls(request: web.Request) -> web.Response:
    limit = int(request.query.get("limit", "50"))
    rows = db.fetchall(
        "SELECT * FROM tool_calls ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    data = [dict(r) for r in rows]
    data.reverse()
    return web.json_response({"tool_calls": data})


async def start_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_get("/api/messages", handle_messages)
    app.router.add_get("/api/tool_calls", handle_tool_calls)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", cfg.ingress_port)
    await site.start()

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
