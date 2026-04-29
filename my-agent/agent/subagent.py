"""Web research sub-agent: isolated tool-use loop with restricted toolset."""

import json
import logging
import time

from openai import AsyncOpenAI

from agent.config import cfg
from agent.memory import log_token_usage, log_tool_call
from agent.tools import execute_tool, get_tool_schemas

logger = logging.getLogger(__name__)

SUBAGENT_TIMEOUT = 180  # seconds
SUBAGENT_TOOLS = {"web_search", "web_fetch", "read_file"}
SUBAGENT_SYSTEM_PROMPT = """\
Tu es un sub-agent de recherche web. Reponds a la question en explorant le web.
Contraintes:
- Maximum 4 web_search et 5 web_fetch.
- Sortie en markdown <= 1500 caracteres.
- Termine par une section "Sources:" listant les URLs utilisees.
Si un hint est fourni, traite-le comme contexte additionnel."""


def _get_cached_tokens(response) -> int:
    try:
        details = response.usage.prompt_tokens_details
        if details and hasattr(details, "cached_tokens"):
            return details.cached_tokens or 0
    except (AttributeError, TypeError):
        pass
    return 0


async def run_research_subagent(
    parent_chat_id: int,
    question: str,
    hint: str | None = None,
) -> str:
    """One-shot research loop. Returns synthesized markdown.

    parent_chat_id is used only to log token usage on the parent chat
    (with a "subagent:" prefixed model tag). No session writes, no
    progress callback, no message persistence.
    """
    user_msg = question if not hint else f"{question}\n\n[hint] {hint}"
    messages = [
        {"role": "system", "content": SUBAGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    client = AsyncOpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_api_base)
    model = cfg.openai_model_light
    tools = get_tool_schemas(include=SUBAGENT_TOOLS)
    tool_kwargs = {"tools": tools} if tools else {}

    start = time.time()
    n_tool_calls = 0
    inp_total = out_total = cached_total = 0

    logger.info(
        "Subagent start parent_chat_id=%s question=%r",
        parent_chat_id,
        question[:80],
    )

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        **tool_kwargs,
    )
    inp_total += response.usage.prompt_tokens
    out_total += response.usage.completion_tokens
    cached_total += _get_cached_tokens(response)

    while response.choices[0].message.tool_calls:
        if time.time() - start > SUBAGENT_TIMEOUT:
            logger.warning(
                "Subagent timeout parent_chat_id=%s question=%r",
                parent_chat_id,
                question[:80],
            )
            break

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            n_tool_calls += 1
            t0 = time.time()
            result = await execute_tool(tool_name, args, {"chat_id": parent_chat_id})
            duration_ms = int((time.time() - t0) * 1000)
            logger.info(
                "Subagent tool parent_chat_id=%s %s [%dms]",
                parent_chat_id,
                tool_name,
                duration_ms,
            )
            if parent_chat_id is not None:
                log_tool_call(
                    chat_id=parent_chat_id,
                    message_id=tc.id,
                    tool_name=tool_name,
                    input_summary=str(args),
                    output_summary=result,
                    success=not result.startswith("Error"),
                    duration_ms=duration_ms,
                    agent_source="subagent",
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            **tool_kwargs,
        )
        inp_total += response.usage.prompt_tokens
        out_total += response.usage.completion_tokens
        cached_total += _get_cached_tokens(response)

    final_text = response.choices[0].message.content or ""

    if parent_chat_id is not None and (inp_total or out_total):
        log_token_usage(
            parent_chat_id,
            f"subagent:{model}",
            inp_total,
            out_total,
            cached_total,
        )

    elapsed_ms = int((time.time() - start) * 1000)
    logger.info(
        "Subagent end parent_chat_id=%s duration=%dms tool_calls=%d output_len=%d",
        parent_chat_id,
        elapsed_ms,
        n_tool_calls,
        len(final_text),
    )

    return final_text
