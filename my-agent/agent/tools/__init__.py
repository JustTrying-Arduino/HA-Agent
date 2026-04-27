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
        return func
    return decorator


def get_tool_schemas(exclude: set[str] | None = None) -> list[dict]:
    exc = exclude or set()
    return [t["schema"] for name, t in TOOLS.items() if name not in exc]


async def execute_tool(name: str, arguments: dict, context: dict | None = None) -> str:
    if name not in TOOLS:
        return f"Error: unknown tool '{name}'"
    handler = TOOLS[name]["handler"]
    try:
        kwargs = dict(arguments)
        if "_context" in inspect.signature(handler).parameters:
            kwargs["_context"] = context or {}
        if inspect.iscoroutinefunction(handler):
            result = await handler(**kwargs)
        else:
            result = await asyncio.to_thread(handler, **kwargs)
        return str(result)
    except Exception as e:
        logger.exception("Tool '%s' failed", name)
        return f"Error executing {name}: {e}"
