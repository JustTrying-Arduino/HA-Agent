"""Pending Degiro orders: persistence + guards + resolve.

The LLM never executes orders. Tools call `create_pending_place` /
`create_pending_cancel`, which validate guards and write a `pending_actions`
row. Execution happens only in `resolve_pending`, called by the Telegram
inline-keyboard callback handler in `agent/telegram.py`. A conditional UPDATE
ensures idempotency against double-clicks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from agent import db, degiro
from agent.config import cfg

logger = logging.getLogger(__name__)


PENDING = "pending"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"
EXPIRED = "expired"
FAILED = "failed"

ACTION_PLACE = "place"
ACTION_CANCEL = "cancel"

TTL_MINUTES = 5
BUY_AMOUNT_CAP_EUR = 1500.0
BUY_QUOTA_PER_24H = 4


class OrderGuardError(Exception):
    """Raised when a pending order is rejected before insertion."""


@dataclass
class ResolveResult:
    status: str  # 'confirmed' | 'cancelled' | 'expired' | 'failed' | 'noop'
    message: str
    telegram_message_id: int | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utc_now().isoformat()


def _expires_iso(ttl_minutes: int = TTL_MINUTES) -> str:
    return (_utc_now() + timedelta(minutes=ttl_minutes)).isoformat()


def validate_kill_switch() -> None:
    if not cfg.degiro_orders_enabled:
        raise OrderGuardError(
            "Le passage d'ordres Degiro est desactive (degiro_orders_enabled=false)."
        )


def _count_buy_confirmed_24h(chat_id: int) -> int:
    cutoff = (_utc_now() - timedelta(hours=24)).isoformat()
    row = db.fetchone(
        """
        SELECT COUNT(*) AS n FROM pending_actions
        WHERE chat_id = ?
          AND action = ?
          AND status = ?
          AND json_extract(payload_json, '$.side') = 'BUY'
          AND resolved_at IS NOT NULL
          AND resolved_at >= ?
        """,
        (chat_id, ACTION_PLACE, CONFIRMED, cutoff),
    )
    return int(row["n"]) if row else 0


def validate_buy_constraints(chat_id: int, size: float, limit_price: float) -> None:
    validate_kill_switch()
    total = float(size) * float(limit_price)
    if total > BUY_AMOUNT_CAP_EUR:
        raise OrderGuardError(
            f"Plafond depasse : montant {total:.2f} EUR > {BUY_AMOUNT_CAP_EUR:.0f} EUR."
        )
    used = _count_buy_confirmed_24h(chat_id)
    if used >= BUY_QUOTA_PER_24H:
        raise OrderGuardError(
            f"Quota atteint : {used}/{BUY_QUOTA_PER_24H} BUY confirmes sur les 24 dernieres heures."
        )


def validate_sell_constraints() -> None:
    validate_kill_switch()


def validate_cancel_constraints() -> None:
    validate_kill_switch()


def _insert_pending(
    *,
    chat_id: int,
    action: str,
    payload: dict,
    preview_text: str,
) -> int:
    cursor = db.execute(
        """
        INSERT INTO pending_actions (
            chat_id, action, payload_json, preview_text, status,
            telegram_message_id, result_text, created_at, expires_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL)
        """,
        (
            chat_id,
            action,
            json.dumps(payload, ensure_ascii=False),
            preview_text,
            PENDING,
            _now_iso(),
            _expires_iso(),
        ),
    )
    db.commit()
    return int(cursor.lastrowid)


def create_pending_place(
    *,
    chat_id: int,
    product_id: str,
    isin: str | None,
    label: str,
    side: str,
    size: float,
    limit_price: float,
    currency: str | None,
) -> tuple[int, str]:
    side_norm = side.upper()
    if side_norm not in ("BUY", "SELL"):
        raise OrderGuardError(f"side doit etre BUY ou SELL, recu {side!r}.")
    if size <= 0:
        raise OrderGuardError("size doit etre strictement positif.")
    if limit_price <= 0:
        raise OrderGuardError("limit_price doit etre strictement positif.")

    if side_norm == "BUY":
        validate_buy_constraints(chat_id, size, limit_price)
    else:
        validate_sell_constraints()

    total = float(size) * float(limit_price)
    cur = currency or "EUR"
    preview_text = (
        f"Confirmer l'ordre ?\n"
        f"{side_norm} {size:g} x {label}"
        + (f" ({isin})" if isin else "")
        + f"\nLimite : {limit_price:.4f} {cur}\n"
        f"Total estime : {total:.2f} {cur}\n"
        f"Type : LIMIT, validite GTC (continu)\n"
        f"Expire dans {TTL_MINUTES} min."
    )
    payload = {
        "product_id": str(product_id),
        "isin": isin,
        "label": label,
        "side": side_norm,
        "size": float(size),
        "limit_price": float(limit_price),
        "currency": cur,
    }
    pending_id = _insert_pending(
        chat_id=chat_id,
        action=ACTION_PLACE,
        payload=payload,
        preview_text=preview_text,
    )
    logger.info(
        "pending place id=%s chat_id=%s side=%s size=%s price=%s",
        pending_id, chat_id, side_norm, size, limit_price,
    )
    return pending_id, preview_text


def create_pending_cancel(
    *,
    chat_id: int,
    order_id: str,
    label: str,
) -> tuple[int, str]:
    validate_cancel_constraints()
    if not order_id:
        raise OrderGuardError("order_id est requis.")
    preview_text = (
        f"Annuler l'ordre ?\n"
        f"{label}\n"
        f"orderId : {order_id}\n"
        f"Expire dans {TTL_MINUTES} min."
    )
    payload = {"order_id": str(order_id), "label": label}
    pending_id = _insert_pending(
        chat_id=chat_id,
        action=ACTION_CANCEL,
        payload=payload,
        preview_text=preview_text,
    )
    logger.info(
        "pending cancel id=%s chat_id=%s order_id=%s", pending_id, chat_id, order_id,
    )
    return pending_id, preview_text


def attach_telegram_message(pending_id: int, telegram_message_id: int) -> None:
    db.execute(
        "UPDATE pending_actions SET telegram_message_id = ? WHERE id = ?",
        (telegram_message_id, pending_id),
    )
    db.commit()


def get_pending(pending_id: int):
    return db.fetchone("SELECT * FROM pending_actions WHERE id = ?", (pending_id,))


def _claim_pending(pending_id: int, chat_id: int, target_status: str) -> bool:
    """Atomic transition pending -> target_status. Returns True if we won the race."""
    cursor = db.execute(
        """
        UPDATE pending_actions
        SET status = ?, resolved_at = ?
        WHERE id = ?
          AND chat_id = ?
          AND status = ?
          AND expires_at > ?
        """,
        (target_status, _now_iso(), pending_id, chat_id, PENDING, _now_iso()),
    )
    db.commit()
    return cursor.rowcount == 1


def _set_result(pending_id: int, *, status: str, result_text: str) -> None:
    db.execute(
        "UPDATE pending_actions SET status = ?, result_text = ? WHERE id = ?",
        (status, result_text, pending_id),
    )
    db.commit()


def _row_status_message(row) -> str:
    status = row["status"]
    if status == CONFIRMED:
        return f"Deja confirme : {row['result_text'] or ''}"
    if status == CANCELLED:
        return "Deja annule."
    if status == EXPIRED:
        return "Demande expiree."
    if status == FAILED:
        return f"Deja en echec : {row['result_text'] or ''}"
    return f"Etat : {status}"


def resolve_pending(
    *,
    pending_id: int,
    chat_id: int,
    decision: str,
) -> ResolveResult:
    """Decision: 'ok' to execute, 'no' to cancel."""
    row = get_pending(pending_id)
    if row is None or row["chat_id"] != chat_id:
        return ResolveResult(status="noop", message="Demande introuvable.")

    telegram_message_id = row["telegram_message_id"]

    if row["status"] != PENDING:
        return ResolveResult(
            status="noop",
            message=_row_status_message(row),
            telegram_message_id=telegram_message_id,
        )

    if decision == "no":
        if not _claim_pending(pending_id, chat_id, CANCELLED):
            row = get_pending(pending_id)
            return ResolveResult(
                status="noop",
                message=_row_status_message(row) if row else "Demande introuvable.",
                telegram_message_id=telegram_message_id,
            )
        return ResolveResult(
            status=CANCELLED,
            message="Annule. Aucune action transmise a Degiro.",
            telegram_message_id=telegram_message_id,
        )

    if decision != "ok":
        return ResolveResult(
            status="noop",
            message=f"Decision inconnue : {decision!r}",
            telegram_message_id=telegram_message_id,
        )

    # Decision == 'ok': claim then execute
    if not _claim_pending(pending_id, chat_id, CONFIRMED):
        row = get_pending(pending_id)
        return ResolveResult(
            status="noop",
            message=_row_status_message(row) if row else "Demande introuvable.",
            telegram_message_id=telegram_message_id,
        )

    payload = json.loads(row["payload_json"])
    action = row["action"]
    try:
        if action == ACTION_PLACE:
            order_id = degiro.place_limit_gtc(
                product_id=payload["product_id"],
                buy_sell=payload["side"],
                size=float(payload["size"]),
                limit_price=float(payload["limit_price"]),
            )
            result_text = f"orderId={order_id}"
            _set_result(pending_id, status=CONFIRMED, result_text=result_text)
            return ResolveResult(
                status=CONFIRMED,
                message=f"Ordre transmis a Degiro. {result_text}",
                telegram_message_id=telegram_message_id,
            )
        if action == ACTION_CANCEL:
            degiro.cancel_order(payload["order_id"])
            result_text = f"orderId={payload['order_id']} annule"
            _set_result(pending_id, status=CONFIRMED, result_text=result_text)
            return ResolveResult(
                status=CONFIRMED,
                message=f"Annulation transmise a Degiro. {result_text}",
                telegram_message_id=telegram_message_id,
            )
        _set_result(pending_id, status=FAILED, result_text=f"Action inconnue: {action}")
        return ResolveResult(
            status=FAILED,
            message=f"Action inconnue : {action}",
            telegram_message_id=telegram_message_id,
        )
    except Exception as exc:
        logger.exception("Execution Degiro echouee pour pending id=%s", pending_id)
        _set_result(pending_id, status=FAILED, result_text=str(exc))
        return ResolveResult(
            status=FAILED,
            message=f"Echec d'execution Degiro : {exc}",
            telegram_message_id=telegram_message_id,
        )


def expire_due_pending() -> list[dict]:
    """Mark expired pending rows and return them so the caller can edit Telegram messages."""
    now = _now_iso()
    rows = db.fetchall(
        "SELECT * FROM pending_actions WHERE status = ? AND expires_at <= ?",
        (PENDING, now),
    )
    if not rows:
        return []
    db.execute(
        "UPDATE pending_actions SET status = ?, resolved_at = ? WHERE status = ? AND expires_at <= ?",
        (EXPIRED, now, PENDING, now),
    )
    db.commit()
    return [dict(row) for row in rows]
