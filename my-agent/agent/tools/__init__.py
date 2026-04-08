"""Tool registry — maps tool names to handlers and OpenAI function-calling schemas."""

import asyncio
import inspect
import logging

logger = logging.getLogger(__name__)

TOOLS: dict[str, dict] = {}


def register(name: str, description: str, parameters: dict):
    """Decorator that registers a tool with its OpenAI function-calling schema."""
    def decorator(func):
        TOOLS[name] = {
            "handler": func,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
        }
        logger.debug("Registered tool: %s", name)
        return func
    return decorator


def get_tool_schemas() -> list[dict]:
    return [t["schema"] for t in TOOLS.values()]


async def execute_tool(name: str, arguments: dict) -> str:
    if name not in TOOLS:
        return f"Error: unknown tool '{name}'"
    handler = TOOLS[name]["handler"]
    try:
        if inspect.iscoroutinefunction(handler):
            result = await handler(**arguments)
        else:
            result = await asyncio.to_thread(handler, **arguments)
        return str(result)
    except Exception as e:
        logger.exception("Tool '%s' failed", name)
        return f"Error executing {name}: {e}"
