# CLAUDE.md — HA-Agent Project Specification

## What is this project?

A minimalist AI agent packaged as a **Home Assistant add-on**. It runs in a Docker container (Alpine), communicates via **Telegram**, executes actions through tools (shell, files, web, reminders), and exposes a dashboard via HA ingress. No agentic framework — just the OpenAI SDK with a custom tool_use loop.

**Current version:** 0.2.6

---

## Architecture overview

```
Telegram (polling) ──► Bot ──► Agent Loop ──► OpenAI API (AsyncOpenAI)
                                   │
                           ┌───────┼───────┐
                           ▼       ▼       ▼
                         exec   files    web       reminders
                         shell  r/w/edit search     create/list/
                                         fetch      update/cancel
                                   │
                             SQLite ◄──── Dashboard (aiohttp, port 8099)
                                   ▲
                           Scheduler (15s poll) ──► triggers due reminders
```

**Single process, single event loop.** The Telegram bot (polling), reminder scheduler, and aiohttp dashboard all run concurrently in the same `asyncio` loop. No threads except for sync tool execution via `asyncio.to_thread`.

---

## Directory structure

```
HA-Agent/
├── CLAUDE.md                          # This file
├── README.md                          # User-facing documentation
├── repository.yaml                    # HA add-on repository metadata
└── my-agent/                          # The add-on (HA expects subdirectory)
    ├── config.yaml                    # HA add-on manifest
    ├── build.yaml                     # Multi-arch build targets
    ├── Dockerfile                     # Alpine + Python, PYTHONPATH=/opt
    ├── run.sh                         # Entrypoint: reads config, launches agent
    ├── requirements.txt               # openai, python-telegram-bot, aiohttp, requests
    ├── translations/en.yaml           # HA UI option labels
    ├── agent/                         # Python package (at /opt/agent/ in container)
    │   ├── __init__.py
    │   ├── main.py                    # Entrypoint: starts all services
    │   ├── config.py                  # Dataclass Config from env vars
    │   ├── db.py                      # SQLite init, WAL mode, helpers
    │   ├── loop.py                    # Agent loop: LLM → tool_use → response (+ progress callbacks)
    │   ├── telegram.py                # Bot: polling, text + audio dispatch + temporary status message
    │   ├── memory.py                  # Session windowing, logging helpers, recent tool calls query
    │   ├── prompt.py                  # System prompt assembly from workspace files + recent tool calls
    │   ├── reminders.py               # Reminder storage, cron parsing, scheduling logic
    │   ├── scheduler.py               # Async scheduler: polls due reminders every 15s
    │   ├── server.py                  # aiohttp dashboard + JSON API
    │   ├── tools/
    │   │   ├── __init__.py            # @register decorator, execute_tool()
    │   │   ├── exec.py                # Shell execution (subprocess, 30s timeout)
    │   │   ├── files.py               # read_file, write_file, edit_file, list_dir
    │   │   ├── web.py                 # web_search (Brave), web_fetch
    │   │   ├── audio.py               # Groq Whisper transcription (not a tool)
    │   │   └── reminders.py           # create/list/update/cancel_reminder tools
    │   └── static/
    │       └── index.html             # Dashboard: vanilla JS, dark mode, ~250 lines
    ├── workspace/                     # Templates → copied to /share/myagent/workspace/
    │   ├── AGENT.md                   # System prompt
    │   ├── USER.md                    # User profile
    │   ├── MEMORY.md                  # Long-term memory
    │   ├── Prompt_Reminder.md         # Extra instructions for reminder-triggered runs
    │   └── skills/                    # Skill directories (each has SKILL.md)
    └── tests/
        └── test_reminders.py
```

---

## Key design decisions

### No framework
The agent loop (`loop.py`) is ~80 lines: call LLM, while tool_calls → execute tools → call LLM again. The tool registry is a `@register` decorator. No LangChain, no CrewAI.

### No sandboxing
The container IS the security boundary. `exec` tool runs `subprocess.run(cmd, shell=True)`. File tools can read/write any path. This is intentional for a single-user home automation agent.

### Polling, not webhooks
Telegram bot uses polling via `python-telegram-bot`. No port exposure, no reverse proxy, works behind NAT.

### Telegram temporary status message
For each incoming Telegram message, the bot immediately sends a lightweight placeholder message (`En reflexion...`) before the LLM response is ready. Only a curated set of long or user-visible tools such as web search, web fetch, and shell execution update that same Telegram message, and they do so immediately when the tool starts. Shorter or less visible tools do not update the placeholder. When the final answer is ready, the placeholder is edited into the final response if it fits in a single Telegram message; otherwise the placeholder is deleted and the response is sent in chunks. This is intentionally not token streaming and should stay low-chatter to avoid slowing the flow.

### SQLite with WAL
Single DB at `/share/myagent/agent.db`. WAL mode for concurrent reads (dashboard + bot). Tables: `messages`, `token_usage`, `tool_calls`, `reminders`.

### Workspace in /share
All prompts, skills, and memory live in `/share/myagent/workspace/` — editable via HA File Editor, Samba, SSH. Templates are copied on first startup only (no overwrite).

### Native reminder scheduler
Replaced the initial Alpine crond approach. Reminders are stored in SQLite, scheduled via an async loop (15s poll). Supports `once` (ISO datetime) and `recurring` (5-field cron). When triggered, the agent runs with `cron=True` which appends `Prompt_Reminder.md` to the system prompt.

### Cached tokens tracked separately
`token_usage` table has a `cached_tokens` column. Extracted from `response.usage.prompt_tokens_details.cached_tokens`. Dashboard shows cached vs. non-cached costs.

---

## How things work

### Startup sequence (main.py)
1. Configure logging (silence httpx/httpcore noise)
2. `init_db()` — create tables if needed
3. Import tool modules (side effect: registers tools)
4. `asyncio.run(run_all())`:
   - Start Telegram bot (initialize → start → start_polling)
   - Start scheduler task (`run_scheduler(bot)`)
   - Start web server task (`start_server()`)
   - Wait for SIGTERM/SIGINT → graceful shutdown

### Agent loop (loop.py)
`async run_agent(chat_id, user_message, cron=False, progress_callback=None) → str`
1. Save user message to DB
2. Build system prompt (standard or cron variant)
3. Load session history (timeout 48h + window 15 messages)
4. Call AsyncOpenAI with tools
5. While tool_calls: optionally notify progress callback → execute → log → optionally notify completion → send results back → call LLM again
6. Log total token usage (input + output + cached, accumulated across all LLM calls)
7. Save assistant response, return it

### Config flow
`config.yaml` options → HA UI → `/data/options.json` → `run.sh` reads with `jq` → env vars → `config.py` `Config.from_env()` → `cfg` singleton.

### Tool registration
```python
@register(name="tool_name", description="...", parameters={...})
def my_tool(arg1: str, _context: dict = None) -> str:
    ...
```
- `_context` is injected automatically if the handler signature accepts it (contains `chat_id`)
- Sync handlers are wrapped with `asyncio.to_thread`
- Tools return strings (errors start with "Error")

### Prompt assembly (prompt.py)
Rebuilt on every request by reading workspace files. `build_system_prompt(chat_id)` accepts an optional `chat_id` to include context-aware sections:
1. Runtime context (current time, timezone, reminder instructions)
2. AGENT.md (identity, rules)
3. USER.md (user profile)
4. skills/*/SKILL.md (each skill)
5. MEMORY.md (long-term context)
6. Recent tool calls (last 5 for this chat_id, max 3h old — from `memory.get_recent_tool_calls`)

Joined with `\n\n---\n\n`. For cron/reminder runs, `Prompt_Reminder.md` is appended.

The recent tool calls section gives the agent visibility into its cross-run tool history, avoiding redundant calls. Controlled by `RECENT_TOOLS_MAX_AGE_HOURS = 3` in `prompt.py`.

### Session management (memory.py)
- **Timeout:** Last message > 48h → archive entire session
- **Window:** Keep last 15 messages
- Only user/assistant messages are persisted. Tool call/result messages are ephemeral within a single loop run.
- `get_recent_tool_calls(chat_id, limit=5)` queries the `tool_calls` table for cross-run tool history, used by `prompt.py` to inject context.

### Dashboard (server.py + static/index.html)
aiohttp serves on port 8099 (HA ingress). API endpoints:
- `/api/stats?period=day|week|month` — token aggregates with cost estimates
- `/api/messages?chat_id=X&limit=50` — history + tool calls
- `/api/tool_calls?limit=50` — audit trail
- `/api/reminders?status=active|all` — reminder list

Frontend is single-file vanilla JS. Uses relative URLs (`./api/...`) for ingress compatibility.

---

## Conventions and rules

### Python
- **Python 3.12+** features OK (type hints, `|` union, dataclasses)
- **Async everywhere**: AsyncOpenAI, async telegram handlers, async scheduler. Sync tool handlers wrapped in `asyncio.to_thread`.
- **Logging**: `logger = logging.getLogger(__name__)` in every module. Log: incoming messages, tool calls (name + duration), outgoing messages, token usage.
- **Error handling**: Catch at service level (`main.py`), tools return error strings instead of raising.
- **Config**: Single `cfg` singleton from `config.py`, read from env vars.
- **Timestamps**: ISO 8601 UTC internally. Local time for display/prompts only.

### Documentation
- **CLAUDE.md must ALWAYS be updated in the same change as any functional evolution.** This is a hard rule, not a best-effort guideline. Every behavior change affecting user flows, tools, architecture, runtime behavior, prompt structure, or operational rules must include the corresponding CLAUDE.md update before the change is considered complete.
- When in doubt, update CLAUDE.md. Stale documentation is worse than verbose documentation.

### Docker / HA add-on
- **Base image**: `ghcr.io/home-assistant/{arch}-base:3.22`
- **Shebang**: `#!/bin/bash` (NOT `#!/usr/bin/with-bashio` — it doesn't exist in the base image). Source bashio manually.
- **init: false** in config.yaml — disables s6-overlay, `CMD ["/run.sh"]` is the entrypoint.
- **PYTHONPATH=/opt** so `agent` package is importable.
- **Config reading**: `run.sh` reads `/data/options.json` with `jq` (NOT bashio::config, which requires Supervisor API access that `init: false` disables).
- **Entry command**: `python3 -m agent.main` (not `python3 /opt/agent/main.py`).

### Workspace files
- Live at `/share/myagent/workspace/` — user-editable, persistent.
- Templates in `my-agent/workspace/` are copied on first boot only (no overwrite).
- **AGENT.md**: Agent identity and behavior rules. Keep concise.
- **USER.md**: Durable user facts only (name, preferences, habits).
- **MEMORY.md**: Non-user durable context (environment, projects, decisions).
- **Skills**: Each in `skills/<name>/SKILL.md`. Narrow, self-contained, action-oriented.

### Version bumping
Always bump `version` in `config.yaml` for every change pushed to GitHub. HA needs a version change to detect updates. Use `"Reconstruire"` button in HA if version cache is stale.

### Dashboard
- Single HTML file, vanilla JS. No framework, no build step, no node_modules.
- Dark mode via CSS custom properties.
- All API URLs relative (`./api/...`) for HA ingress compatibility.
- Sticky header: title + tab bar stay fixed at the top when scrolling.
- Dates shown as `dd/mm HH:MM` in both messages and tool calls tables.
- Tool calls table uses compact single-line rows with inline "Voir plus" expand for input details.
- **Mock data for local dev**: `fetchOrMock()` helper tries real API calls first; on failure (no backend = local dev), falls back to built-in mock data. Mocks are never used in production since the real API responds. No config flag needed.

### Tools
- Each tool in its own file under `agent/tools/`.
- Registered via `@register` decorator at import time.
- Conditional registration: `web_search` only if `cfg.brave_api_key` is set.
- Tool imports happen in `main.py` for side effects.
- Max output limits: exec 10k chars, read_file 50k chars, web_fetch 20k chars.
- `audio.py` is NOT a tool — it's a utility for Telegram voice message transcription.
- Telegram-facing tool progress uses a fixed mapping from internal tool names to short French user-facing labels.

### Reminders
- Stored in SQLite `reminders` table, not in filesystem.
- Schedule kinds: `once` (ISO datetime) or `recurring` (5-field cron).
- Scheduler polls every 15 seconds.
- When triggered, the scheduler injects a structured message with reminder metadata and instruction:
  ```
  [REMINDER TRIGGER] id=#12 title="Sortir les poubelles" kind=once
  [REMINDER INSTRUCTION] Envoyer un message : Sortir les poubelles !
  ```
  This lets the agent know which reminder triggered it without needing to call `list_reminders`. The call is `run_agent(chat_id, context, cron=True)` with no `progress_callback`.
- One-time reminders archived after execution. Recurring ones compute next_run_at.
- Archived/cancelled reminders purged after 48h.

---

## What is NOT implemented (future work)

- **Home Assistant tools** (ha_call_service, ha_get_states) — deferred to a future iteration.
- **Streaming** Telegram token-by-token responses (currently uses a temporary placeholder message and only shows slow tool phases).
- **Multi-agent** or multi-model support.
- **Webhook** mode for Telegram.

---

## Quick reference: files to touch for common changes

| Task | Files |
|------|-------|
| Add a new tool | `agent/tools/new_tool.py` + import in `main.py` |
| Change system prompt | `workspace/AGENT.md` (template) or edit in /share at runtime |
| Add HA config option | `config.yaml` (options + schema) + `run.sh` (export) + `config.py` (field) + `translations/en.yaml` |
| Modify agent loop behavior | `agent/loop.py` |
| Change session rules | `agent/memory.py` (timeout, window size) |
| Add dashboard endpoint | `agent/server.py` + `agent/static/index.html` |
| Modify reminder logic | `agent/reminders.py` (storage) + `agent/tools/reminders.py` (LLM tools) + `agent/scheduler.py` (execution) |
| Bump version | `my-agent/config.yaml` → version field |
