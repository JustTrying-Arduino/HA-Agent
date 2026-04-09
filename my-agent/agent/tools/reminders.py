"""Tools: create and manage reminders."""

from agent import reminders
from agent.tools import register


def _chat_id_from_context(context: dict | None) -> int:
    chat_id = (context or {}).get("chat_id")
    if chat_id is None:
        raise ValueError("Missing chat context")
    return int(chat_id)


@register(
    name="create_reminder",
    description=(
        "Create a one-time or recurring reminder for the current chat. "
        "When the reminder triggers at the scheduled time, the agent will be invoked again "
        "and must execute the provided instruction automatically, so the instruction should "
        "be explicit, self-contained, and action-oriented."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short reminder title"},
            "instruction": {
                "type": "string",
                "description": (
                    "Precise, self-contained instruction that the agent will execute later "
                    "when the reminder triggers. Include the exact task, expected outcome, "
                    "and any useful context because the future run may not have the current "
                    "conversation details."
                ),
            },
            "schedule_kind": {
                "type": "string",
                "enum": ["once", "recurring"],
                "description": "Whether this reminder runs once or repeatedly",
            },
            "run_at": {
                "type": "string",
                "description": "ISO datetime for one-time reminders, for example 2026-04-08 20:30",
            },
            "cron_expr": {
                "type": "string",
                "description": "Standard 5-field cron expression for recurring reminders",
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone name like Europe/Paris. Optional.",
            },
        },
        "required": ["title", "instruction", "schedule_kind"],
    },
)
def create_reminder(
    title: str,
    instruction: str,
    schedule_kind: str,
    run_at: str | None = None,
    cron_expr: str | None = None,
    timezone: str | None = None,
    _context: dict | None = None,
) -> str:
    reminder = reminders.create_reminder(
        chat_id=_chat_id_from_context(_context),
        title=title,
        instruction=instruction,
        schedule_kind=schedule_kind,
        run_at=run_at,
        cron_expr=cron_expr,
        timezone_name=timezone,
    )
    return "Reminder created successfully.\n" + reminders.format_reminder(reminder)


@register(
    name="list_reminders",
    description="List reminders for the current chat.",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["all", "active", "archived", "cancelled"],
                "description": "Filter reminders by status. Defaults to active.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of reminders to return",
                "minimum": 1,
                "maximum": 100,
            },
        },
    },
)
def list_reminders(
    status: str = "active",
    limit: int = 20,
    _context: dict | None = None,
) -> str:
    filter_status = None if status == "all" else status
    rows = reminders.list_reminders(
        chat_id=_chat_id_from_context(_context),
        status=filter_status,
        limit=limit,
    )
    if not rows:
        return "No reminders found."
    return "\n\n".join(reminders.format_reminder(row) for row in rows)


@register(
    name="update_reminder",
    description="Update an existing active reminder in the current chat.",
    parameters={
        "type": "object",
        "properties": {
            "reminder_id": {"type": "integer", "description": "Reminder ID to update"},
            "title": {"type": "string", "description": "New title"},
            "instruction": {"type": "string", "description": "New reminder instruction"},
            "schedule_kind": {
                "type": "string",
                "enum": ["once", "recurring"],
                "description": "Optional new schedule type",
            },
            "run_at": {
                "type": "string",
                "description": "New ISO datetime if the reminder should run once",
            },
            "cron_expr": {
                "type": "string",
                "description": "New standard 5-field cron expression for recurring reminders",
            },
            "timezone": {
                "type": "string",
                "description": "New timezone name like Europe/Paris",
            },
        },
        "required": ["reminder_id"],
    },
)
def update_reminder(
    reminder_id: int,
    title: str | None = None,
    instruction: str | None = None,
    schedule_kind: str | None = None,
    run_at: str | None = None,
    cron_expr: str | None = None,
    timezone: str | None = None,
    _context: dict | None = None,
) -> str:
    reminder = reminders.update_reminder(
        chat_id=_chat_id_from_context(_context),
        reminder_id=reminder_id,
        title=title,
        instruction=instruction,
        schedule_kind=schedule_kind,
        run_at=run_at,
        cron_expr=cron_expr,
        timezone_name=timezone,
    )
    return "Reminder updated successfully.\n" + reminders.format_reminder(reminder)


@register(
    name="cancel_reminder",
    description="Cancel a reminder in the current chat so it no longer runs.",
    parameters={
        "type": "object",
        "properties": {
            "reminder_id": {"type": "integer", "description": "Reminder ID to cancel"},
        },
        "required": ["reminder_id"],
    },
)
def cancel_reminder(reminder_id: int, _context: dict | None = None) -> str:
    reminder = reminders.cancel_reminder(
        chat_id=_chat_id_from_context(_context),
        reminder_id=reminder_id,
    )
    return "Reminder cancelled successfully.\n" + reminders.format_reminder(reminder)
