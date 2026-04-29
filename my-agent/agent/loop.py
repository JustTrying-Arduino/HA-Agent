"""Agent loop: message → LLM → tool_use → response."""

import json
import time
import logging
import inspect
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from agent.config import cfg
from agent.memory import (
    expire_session_if_needed,
    get_session_messages,
    save_message,
    log_token_usage,
    log_tool_call,
)
from agent.prompt import build_system_prompt, build_cron_prompt
from agent.tools import get_tool_schemas, execute_tool

logger = logging.getLogger(__name__)

LOOP_TIMEOUT = 300  # 5 minutes max per agent run
ProgressCallback = Callable[[str, dict], Awaitable[None] | None]
DEBUG_TEXT_LIMIT = 4000


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
    # Archive an expired session before the new user message becomes the latest activity.
    expire_session_if_needed(chat_id)

    # Save user message
    save_message(chat_id, "user", user_message)

    # Build system prompt
    system_prompt = build_cron_prompt(chat_id) if cron else build_system_prompt(chat_id)

    # Build messages list
    session = get_session_messages(chat_id)
    messages = [{"role": "system", "content": system_prompt}] + session

    # Prepare OpenAI client
    client = AsyncOpenAI(api_key=cfg.openai_api_key, base_url=cfg.openai_api_base)

    # Model routing
    current_model = cfg.openai_model_light
    escalated = False
    n_tool_calls = 0

    logger.info("Agent run start chat_id=%s model=%s", chat_id, current_model)

    # Per-model token accumulators: {model: [input, output, cached]}
    token_accum: dict[str, list[int]] = {}

    def _add_tokens(model: str, inp: int, out: int, cached: int):
        if model not in token_accum:
            token_accum[model] = [0, 0, 0]
        token_accum[model][0] += inp
        token_accum[model][1] += out
        token_accum[model][2] += cached

    def _build_tool_kwargs() -> dict:
        exclude = {"escalate_model"} if escalated else set()
        schemas = get_tool_schemas(exclude=exclude)
        return {"tools": schemas} if schemas else {}

    start_time = time.time()

    _log_llm_request(chat_id, current_model, messages, _build_tool_kwargs().get("tools"))

    # First LLM call
    response = await client.chat.completions.create(
        model=current_model,
        messages=messages,
        **_build_tool_kwargs(),
    )
    _log_llm_response(chat_id, response)
    _add_tokens(current_model, response.usage.prompt_tokens,
                response.usage.completion_tokens, _get_cached_tokens(response))

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

            n_tool_calls += 1
            logger.info(
                "Tool call chat_id=%s %s(%s)",
                chat_id, tool_name, _truncate(str(arguments), 200),
            )
            await _notify_progress(progress_callback, "tool_start", tool_name=tool_name)

            t0 = time.time()
            result = await execute_tool(tool_name, arguments, {"chat_id": chat_id})
            duration_ms = int((time.time() - t0) * 1000)
            success = not result.startswith("Error")

            logger.info(
                "Tool result chat_id=%s %s -> %s [%dms]",
                chat_id, tool_name, _truncate(result, 200), duration_ms,
            )

            log_tool_call(
                chat_id=chat_id,
                message_id=tc.id,
                tool_name=tool_name,
                input_summary=str(arguments),
                output_summary=result,
                success=success,
                duration_ms=duration_ms,
                agent_source="main",
            )

            # Detect escalation
            if tool_name == "escalate_model" and not escalated:
                current_model = cfg.openai_model
                escalated = True
                logger.info("Model escalated to %s for chat_id=%s", current_model, chat_id)

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

        # Next LLM call (with updated model and tools)
        _log_llm_request(chat_id, current_model, messages, _build_tool_kwargs().get("tools"))
        response = await client.chat.completions.create(
            model=current_model,
            messages=messages,
            **_build_tool_kwargs(),
        )
        _log_llm_response(chat_id, response)
        _add_tokens(current_model, response.usage.prompt_tokens,
                    response.usage.completion_tokens, _get_cached_tokens(response))

    # Extract final response
    final_text = response.choices[0].message.content or ""

    # Log tokens per model
    for model, (inp, out, cached) in token_accum.items():
        if inp or out:
            log_token_usage(chat_id, model, inp, out, cached)

    # Save assistant message with model info
    save_message(chat_id, "assistant", final_text, model=current_model)

    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "Agent run end chat_id=%s duration=%dms tool_calls=%d escalated=%s",
        chat_id, elapsed_ms, n_tool_calls, escalated,
    )

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


def _serialize_message(message) -> dict:
    if isinstance(message, dict):
        return message
    try:
        return message.model_dump(mode="json")
    except Exception:
        return {"role": getattr(message, "role", "?"), "content": str(message)}


def _log_llm_request(chat_id: int, model: str, messages: list, tools: list[dict] | None) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    logger.debug(
        "LLM request chat_id=%s model=%s n_messages=%d n_tools=%d",
        chat_id, model, len(messages), len(tools or []),
    )

    try:
        payload = {
            "messages": [_serialize_message(m) for m in messages],
            "tools": tools or [],
        }
        logger.debug(
            "LLM request payload chat_id=%s %s",
            chat_id,
            _truncate(json.dumps(payload, ensure_ascii=True), DEBUG_TEXT_LIMIT),
        )
    except Exception:
        logger.debug("LLM request payload chat_id=%s (serialization failed)", chat_id)


def _log_llm_response(chat_id: int, response) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return

    finish_reason = "?"
    content_len = 0
    n_tool_calls = 0
    try:
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", "?") or "?"
        message = choice.message
        content_len = len(getattr(message, "content", None) or "")
        n_tool_calls = len(getattr(message, "tool_calls", None) or [])
    except Exception:
        pass

    logger.debug(
        "LLM response chat_id=%s finish_reason=%s content_len=%d n_tool_calls=%d",
        chat_id, finish_reason, content_len, n_tool_calls,
    )

    try:
        payload = response.model_dump(mode="json")
        logger.debug(
            "LLM response payload chat_id=%s %s",
            chat_id,
            _truncate(json.dumps(payload, ensure_ascii=True), DEBUG_TEXT_LIMIT),
        )
    except Exception:
        logger.debug("LLM response payload chat_id=%s (serialization failed)", chat_id)
