"""Reminder storage and scheduling helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agent import db
from agent.config import cfg

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_CANCELLED = "cancelled"
VALID_STATUSES = {STATUS_ACTIVE, STATUS_ARCHIVED, STATUS_CANCELLED}
VALID_SCHEDULE_KINDS = {"once", "recurring"}
ARCHIVE_RETENTION_HOURS = 48


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat()


def get_timezone(timezone_name: str | None = None) -> ZoneInfo:
    name = timezone_name or cfg.timezone or "UTC"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc


def parse_run_at(run_at: str, timezone_name: str | None = None) -> datetime:
    if not run_at or not run_at.strip():
        raise ValueError("run_at is required for one-time reminders")

    raw = run_at.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            "Invalid run_at format. Use ISO date/time like 2026-04-08 20:30."
        ) from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_timezone(timezone_name))

    dt_utc = dt.astimezone(timezone.utc)
    if dt_utc <= utc_now():
        raise ValueError("run_at must be in the future")
    return dt_utc


def validate_cron_expr(expr: str) -> str:
    cron_expr = (expr or "").strip()
    if not cron_expr:
        raise ValueError("cron_expr is required for recurring reminders")
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError("Invalid cron_expr. Expected standard 5-field cron syntax.")
    _parse_cron_fields(cron_expr)
    return cron_expr


def _expand_cron_field(field: str, minimum: int, maximum: int, *, allow_sunday_7: bool = False) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        token = part.strip()
        if not token:
            raise ValueError("Empty cron field component")

        if "/" in token:
            base, step_raw = token.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                raise ValueError("Cron step must be positive")
        else:
            base = token
            step = 1

        if base == "*":
            start = minimum
            end = maximum
        elif "-" in base:
            start_raw, end_raw = base.split("-", 1)
            start = int(start_raw)
            end = int(end_raw)
        else:
            start = int(base)
            end = int(base)

        if allow_sunday_7 and start == 7:
            start = 0
        if allow_sunday_7 and end == 7:
            end = 0

        if start < minimum or start > maximum or end < minimum or end > maximum:
            raise ValueError("Cron field value out of range")
        if start > end and not allow_sunday_7:
            raise ValueError("Invalid cron range")

        if start <= end:
            ranges = [range(start, end + 1, step)]
        else:
            ranges = [range(start, maximum + 1, step), range(minimum, end + 1, step)]

        for current_range in ranges:
            for value in current_range:
                values.add(0 if allow_sunday_7 and value == 7 else value)

    return values


def _parse_cron_fields(expr: str) -> dict:
    minute, hour, day, month, weekday = expr.split()
    return {
        "minute_raw": minute,
        "hour_raw": hour,
        "day_raw": day,
        "month_raw": month,
        "weekday_raw": weekday,
        "minute": _expand_cron_field(minute, 0, 59),
        "hour": _expand_cron_field(hour, 0, 23),
        "day": _expand_cron_field(day, 1, 31),
        "month": _expand_cron_field(month, 1, 12),
        "weekday": _expand_cron_field(weekday, 0, 6, allow_sunday_7=True),
    }


def _matches_cron(dt_local: datetime, parsed: dict) -> bool:
    cron_weekday = (dt_local.weekday() + 1) % 7
    day_match = dt_local.day in parsed["day"]
    weekday_match = cron_weekday in parsed["weekday"]
    day_any = parsed["day_raw"] == "*"
    weekday_any = parsed["weekday_raw"] == "*"

    if dt_local.minute not in parsed["minute"]:
        return False
    if dt_local.hour not in parsed["hour"]:
        return False
    if dt_local.month not in parsed["month"]:
        return False

    if day_any and weekday_any:
        return True
    if day_any:
        return weekday_match
    if weekday_any:
        return day_match
    return day_match or weekday_match


def compute_next_run(
    schedule_kind: str,
    schedule_expr: str,
    timezone_name: str,
    *,
    after: datetime | None = None,
) -> datetime:
    if schedule_kind not in VALID_SCHEDULE_KINDS:
        raise ValueError(f"Invalid schedule_kind: {schedule_kind}")

    if schedule_kind == "once":
        return parse_run_at(schedule_expr, timezone_name)

    base_utc = after or utc_now()
    tz = get_timezone(timezone_name)
    parsed = _parse_cron_fields(schedule_expr)
    current = base_utc.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)

    for _ in range(60 * 24 * 366 * 5):
        if _matches_cron(current, parsed):
            return current.astimezone(timezone.utc)
        current += timedelta(minutes=1)

    raise ValueError("Unable to compute next run for cron expression")


def serialize_row(row) -> dict:
    return dict(row) if row is not None else {}


def format_timestamp(iso_value: str | None, timezone_name: str) -> str:
    if not iso_value:
        return "-"
    dt = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    return dt.astimezone(get_timezone(timezone_name)).strftime("%Y-%m-%d %H:%M %Z")


def format_reminder(row) -> str:
    reminder = serialize_row(row)
    timezone_name = reminder["timezone"]
    return (
        f"[#{reminder['id']}] {reminder['title']} "
        f"({reminder['status']}, {reminder['schedule_kind']})\n"
        f"Instruction: {reminder['instruction']}\n"
        f"Next run: {format_timestamp(reminder.get('next_run_at'), timezone_name)}\n"
        f"Schedule: {reminder['schedule_expr']} [{timezone_name}]"
    )


def _resolve_schedule(
    schedule_kind: str,
    *,
    run_at: str | None,
    cron_expr: str | None,
    timezone_name: str,
) -> tuple[str, datetime]:
    if schedule_kind == "once":
        next_run = parse_run_at(run_at or "", timezone_name)
        return next_run.isoformat(), next_run

    if schedule_kind == "recurring":
        expr = validate_cron_expr(cron_expr or "")
        next_run = compute_next_run("recurring", expr, timezone_name)
        return expr, next_run

    raise ValueError("schedule_kind must be 'once' or 'recurring'")


def _fetch_one_for_chat(reminder_id: int, chat_id: int):
    return db.fetchone(
        "SELECT * FROM reminders WHERE id = ? AND chat_id = ?",
        (reminder_id, chat_id),
    )


def create_reminder(
    *,
    chat_id: int,
    title: str,
    instruction: str,
    schedule_kind: str,
    run_at: str | None = None,
    cron_expr: str | None = None,
    timezone_name: str | None = None,
) -> dict:
    if not title.strip():
        raise ValueError("title is required")
    if not instruction.strip():
        raise ValueError("instruction is required")

    tz_name = timezone_name or cfg.timezone
    schedule_expr, next_run = _resolve_schedule(
        schedule_kind,
        run_at=run_at,
        cron_expr=cron_expr,
        timezone_name=tz_name,
    )
    timestamp = now_iso()

    cursor = db.execute(
        """
        INSERT INTO reminders (
            chat_id, title, instruction, schedule_kind, schedule_expr,
            timezone, status, next_run_at, last_run_at, archived_at,
            created_at, updated_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
        """,
        (
            chat_id,
            title.strip(),
            instruction.strip(),
            schedule_kind,
            schedule_expr,
            tz_name,
            STATUS_ACTIVE,
            next_run.isoformat(),
            timestamp,
            timestamp,
        ),
    )
    db.commit()
    reminder = db.fetchone("SELECT * FROM reminders WHERE id = ?", (cursor.lastrowid,))
    logger.info("Reminder created: id=%s chat_id=%s", cursor.lastrowid, chat_id)
    return serialize_row(reminder)


def list_reminders(
    *,
    chat_id: int | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict]:
    if status and status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    params: list = []
    sql = "SELECT * FROM reminders"
    clauses = []

    if chat_id is not None:
        clauses.append("chat_id = ?")
        params.append(chat_id)
    if status:
        clauses.append("status = ?")
        params.append(status)

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)

    sql += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'archived' THEN 1 ELSE 2 END, next_run_at, created_at DESC LIMIT ?"
    params.append(limit)

    rows = db.fetchall(sql, tuple(params))
    return [serialize_row(row) for row in rows]


def update_reminder(
    *,
    chat_id: int,
    reminder_id: int,
    title: str | None = None,
    instruction: str | None = None,
    schedule_kind: str | None = None,
    run_at: str | None = None,
    cron_expr: str | None = None,
    timezone_name: str | None = None,
) -> dict:
    current = _fetch_one_for_chat(reminder_id, chat_id)
    if current is None:
        raise ValueError(f"Reminder #{reminder_id} not found")
    if current["status"] != STATUS_ACTIVE:
        raise ValueError("Only active reminders can be updated")

    next_title = title.strip() if title is not None else current["title"]
    next_instruction = (
        instruction.strip() if instruction is not None else current["instruction"]
    )
    if not next_title:
        raise ValueError("title is required")
    if not next_instruction:
        raise ValueError("instruction is required")
    next_schedule_kind = schedule_kind or current["schedule_kind"]
    next_timezone = timezone_name or current["timezone"]

    effective_run_at = run_at
    effective_cron_expr = cron_expr
    if next_schedule_kind == "once" and effective_run_at is None:
        effective_run_at = current["schedule_expr"] if current["schedule_kind"] == "once" else None
    if next_schedule_kind == "recurring" and effective_cron_expr is None:
        effective_cron_expr = current["schedule_expr"] if current["schedule_kind"] == "recurring" else None

    schedule_expr, next_run = _resolve_schedule(
        next_schedule_kind,
        run_at=effective_run_at,
        cron_expr=effective_cron_expr,
        timezone_name=next_timezone,
    )
    updated_at = now_iso()

    db.execute(
        """
        UPDATE reminders
        SET title = ?, instruction = ?, schedule_kind = ?, schedule_expr = ?,
            timezone = ?, next_run_at = ?, updated_at = ?, last_error = NULL
        WHERE id = ? AND chat_id = ?
        """,
        (
            next_title,
            next_instruction,
            next_schedule_kind,
            schedule_expr,
            next_timezone,
            next_run.isoformat(),
            updated_at,
            reminder_id,
            chat_id,
        ),
    )
    db.commit()
    reminder = _fetch_one_for_chat(reminder_id, chat_id)
    logger.info("Reminder updated: id=%s chat_id=%s", reminder_id, chat_id)
    return serialize_row(reminder)


def cancel_reminder(*, chat_id: int, reminder_id: int) -> dict:
    current = _fetch_one_for_chat(reminder_id, chat_id)
    if current is None:
        raise ValueError(f"Reminder #{reminder_id} not found")
    if current["status"] == STATUS_CANCELLED:
        return serialize_row(current)
    if current["status"] != STATUS_ACTIVE:
        raise ValueError("Only active reminders can be cancelled")

    cancelled_at = now_iso()
    db.execute(
        """
        UPDATE reminders
        SET status = ?, next_run_at = NULL, archived_at = ?, updated_at = ?, last_error = NULL
        WHERE id = ? AND chat_id = ?
        """,
        (STATUS_CANCELLED, cancelled_at, cancelled_at, reminder_id, chat_id),
    )
    db.commit()
    reminder = _fetch_one_for_chat(reminder_id, chat_id)
    logger.info("Reminder cancelled: id=%s chat_id=%s", reminder_id, chat_id)
    return serialize_row(reminder)


def get_due_reminders(limit: int = 10) -> list[dict]:
    rows = db.fetchall(
        """
        SELECT * FROM reminders
        WHERE status = ? AND next_run_at IS NOT NULL AND next_run_at <= ?
        ORDER BY next_run_at ASC
        LIMIT ?
        """,
        (STATUS_ACTIVE, now_iso(), limit),
    )
    return [serialize_row(row) for row in rows]


def mark_executed(reminder: dict, *, error: str | None = None) -> dict:
    executed_at = now_iso()
    reminder_id = reminder["id"]

    if reminder["schedule_kind"] == "once":
        db.execute(
            """
            UPDATE reminders
            SET status = ?, last_run_at = ?, archived_at = ?, updated_at = ?,
                next_run_at = NULL, last_error = ?
            WHERE id = ?
            """,
            (
                STATUS_ARCHIVED,
                executed_at,
                executed_at,
                executed_at,
                error,
                reminder_id,
            ),
        )
    else:
        base = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        next_run = compute_next_run(
            "recurring",
            reminder["schedule_expr"],
            reminder["timezone"],
            after=base,
        )
        db.execute(
            """
            UPDATE reminders
            SET last_run_at = ?, updated_at = ?, next_run_at = ?, last_error = ?
            WHERE id = ?
            """,
            (
                executed_at,
                executed_at,
                next_run.isoformat(),
                error,
                reminder_id,
            ),
        )

    db.commit()
    row = db.fetchone("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    return serialize_row(row)


def purge_archived_reminders(hours: int = ARCHIVE_RETENTION_HOURS) -> int:
    cutoff = (utc_now() - timedelta(hours=hours)).isoformat()
    cursor = db.execute(
        """
        DELETE FROM reminders
        WHERE status IN (?, ?)
          AND archived_at IS NOT NULL
          AND archived_at <= ?
        """,
        (STATUS_ARCHIVED, STATUS_CANCELLED, cutoff),
    )
    db.commit()
    deleted = cursor.rowcount or 0
    if deleted:
        logger.info("Purged %s archived reminders", deleted)
    return deleted
