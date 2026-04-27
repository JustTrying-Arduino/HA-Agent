"""Tool: web_research — spawn parallel web research sub-agents."""

import asyncio
import logging

from agent.subagent import run_research_subagent
from agent.tools import register

logger = logging.getLogger(__name__)

MAX_CONCURRENT_SUBAGENTS = 3


@register(
    name="web_research",
    description=(
        "Lance des sub-agents de recherche web en parallele pour une ou plusieurs questions. "
        "Chaque sub-agent fait sa propre boucle web_search/web_fetch et retourne une synthese courte. "
        "Utilise ce tool des que tu as >= 2 angles a explorer ou quand la recherche demande "
        "plusieurs fetch profonds. Pour une question simple et factuelle, web_search direct suffit."
    ),
    parameters={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Question de recherche autonome",
                        },
                        "hint": {
                            "type": "string",
                            "description": "Contexte optionnel (ticker, periode, skill path)",
                        },
                    },
                    "required": ["question"],
                },
                "minItems": 1,
                "maxItems": 5,
            },
        },
        "required": ["tasks"],
    },
)
async def web_research(tasks: list, _context: dict) -> str:
    parent_chat_id = _context.get("chat_id")
    sem = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)

    async def _run_one(task: dict) -> str:
        async with sem:
            try:
                return await run_research_subagent(
                    parent_chat_id,
                    task["question"],
                    task.get("hint"),
                )
            except Exception as e:
                logger.exception(
                    "Subagent failed for question=%r", task.get("question", "")[:80],
                )
                return f"[ERREUR] {e}"

    results = await asyncio.gather(*[_run_one(t) for t in tasks])

    parts = []
    for task, result in zip(tasks, results):
        parts.append(f"## {task['question']}")
        parts.append(result)
        parts.append("")
    return "\n".join(parts).strip()
