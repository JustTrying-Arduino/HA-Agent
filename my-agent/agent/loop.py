"""Agent loop: message → LLM → tool_use → response."""

import json
import time
import logging
import inspect
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from agent.config import cfg
from agent.memory import get_session_messages, save_message, log_token_usage, log_tool_call
from agent.prompt import build_system_prompt, build_cron_prompt
from agent.tools import get_tool_schemas, execute_tool

logger = logging.getLogger(__name__)

LOOP_TIMEOUT = 300  # 5 minutes max per agent run
ProgressCallback = Callable[[str, dict], Awaitable[None] | None]


async def run_agent(
    chat_id: int,
    user_message: str,
    cron: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Run the agent loop for a single user message. Returns the final response text."""
    try:
        return await _run_agent_inner(chat_id, user_message, cron, progress_callback)
    except Exception as e:
        logger.exception("Agent loop error for chat_id=%s", chat_id)
        return f"An error occurred: {e}"


async def _run_agent_inner(
    chat_id: int,
    user_message: str,
    cron: bool,
    progress_callback: ProgressCallback | None,
) -> str:
    # Save user message
    save_message(chat_id, "user", user_message)

    # Build system prompt
    system_prompt = build_cron_prompt() if cron else build_system_prompt()

    # Build messages list
    session = get_session_messages(chat_id)
    messages = [{"role": "system", "content": system_prompt}] + session

    # Prepare OpenAI client
    client = AsyncOpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_api_base)
    tools = get_tool_schemas()
    tool_kwargs = {"tools": tools} if tools else {}

    # Token accumulators
    total_input = 0
    total_output = 0
    total_cached = 0

    start_time = time.time()

    # First LLM call
    response = await client.chat.completions.create(
        model=cfg.openai_model,
        messages=messages,
        **tool_kwargs,
    )
    total_input += response.usage.prompt_tokens
    total_output += response.usage.completion_tokens
    total_cached += _get_cached_tokens(response)

    # Tool use loop
    while response.choices[0].message.tool_calls:
        if time.time() - start_time > LOOP_TIMEOUT:
            logger.warning("Agent loop timeout for chat_id=%s", chat_id)
            break

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        for tc in assistant_msg.tool_calls:
            tool_name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            logger.info("Tool call: %s(%s)", tool_name, _truncate(str(arguments), 200))
            await _notify_progress(progress_callback, "tool_start", tool_name=tool_name)

            t0 = time.time()
            result = await execute_tool(tool_name, arguments, {"chat_id": chat_id})
            duration_ms = int((time.time() - t0) * 1000)
            success = not result.startswith("Error")

            logger.info(
                "Tool result: %s -> %s [%dms]",
                tool_name, _truncate(result, 200), duration_ms,
            )

            log_tool_call(
                chat_id=chat_id,
                message_id=tc.id,
                tool_name=tool_name,
                input_summary=str(arguments),
                output_summary=result,
                success=success,
                duration_ms=duration_ms,
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
            await _notify_progress(
                progress_callback,
                "tool_end",
                tool_name=tool_name,
                duration_ms=duration_ms,
                success=success,
            )

        # Next LLM call
        response = await client.chat.completions.create(
            model=cfg.openai_model,
            messages=messages,
            **tool_kwargs,
        )
        total_input += response.usage.prompt_tokens
        total_output += response.usage.completion_tokens
        total_cached += _get_cached_tokens(response)

    # Extract final response
    final_text = response.choices[0].message.content or ""

    # Log tokens
    log_token_usage(chat_id, cfg.openai_model, total_input, total_output, total_cached)

    # Save assistant message
    save_message(chat_id, "assistant", final_text)

    return final_text


def _get_cached_tokens(response) -> int:
    """Extract cached tokens from response usage, handling missing fields."""
    try:
        details = response.usage.prompt_tokens_details
        if details and hasattr(details, "cached_tokens"):
            return details.cached_tokens or 0
    except (AttributeError, TypeError):
        pass
    return 0


def _truncate(text: str, max_len: int) -> str:
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


async def _notify_progress(
    progress_callback: ProgressCallback | None,
    event: str,
    **payload,
):
    if progress_callback is None:
        return

    try:
        maybe_awaitable = progress_callback(event, payload)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
    except Exception:
        logger.exception("Progress callback failed for event=%s", event)
