"""SQLite database initialization and helpers."""

import sqlite3
import logging

from agent.config import cfg

logger = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(cfg.db_path, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            archived INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_messages_chat_archived
            ON messages(chat_id, archived);

        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cached_tokens INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id TEXT,
            tool_name TEXT NOT NULL,
            input_summary TEXT,
            output_summary TEXT,
            success INTEGER NOT NULL,
            duration_ms INTEGER NOT NULL,
            agent_source TEXT NOT NULL DEFAULT 'main'
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            instruction TEXT NOT NULL,
            schedule_kind TEXT NOT NULL,
            schedule_expr TEXT NOT NULL,
            timezone TEXT NOT NULL,
            status TEXT NOT NULL,
            next_run_at TEXT,
            last_run_at TEXT,
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_reminders_status_next_run
            ON reminders(status, next_run_at);

        CREATE INDEX IF NOT EXISTS idx_reminders_chat_status
            ON reminders(chat_id, status);

        CREATE TABLE IF NOT EXISTS degiro_products (
            query_norm TEXT PRIMARY KEY,
            isin TEXT,
            product_id TEXT,
            vwd_id TEXT,
            vwd_identifier_type TEXT,
            symbol TEXT,
            name TEXT,
            currency TEXT,
            exchange_id TEXT,
            history_ok INTEGER NOT NULL DEFAULT 0,
            metadata_ok INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS degiro_prices (
            vwd_id TEXT NOT NULL,
            resolution TEXT NOT NULL,
            ts TEXT NOT NULL,
            close REAL NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            volume REAL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (vwd_id, resolution, ts)
        );

        CREATE INDEX IF NOT EXISTS idx_degiro_prices_vwd_res_ts
            ON degiro_prices (vwd_id, resolution, ts DESC);

        DROP TABLE IF EXISTS market_eod_prices;
        DROP TABLE IF EXISTS market_api_usage;
    """)
    db.commit()

    # Migrations
    try:
        db.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        db.commit()
        logger.info("Migration: added 'model' column to messages table")
    except Exception:
        pass  # Column already exists

    try:
        db.execute(
            "ALTER TABLE tool_calls ADD COLUMN agent_source TEXT NOT NULL DEFAULT 'main'"
        )
        db.commit()
        logger.info("Migration: added 'agent_source' column to tool_calls table")
    except Exception:
        pass  # Column already exists

    try:
        db.execute("ALTER TABLE degiro_products ADD COLUMN vwd_identifier_type TEXT")
        db.commit()
        # First run with the new column: existing rows were resolved without
        # vwd_identifier_type and may carry history_ok=0 / metadata_ok=0 for
        # US securities. Purge so they get re-resolved with the correct prefix.
        db.execute("DELETE FROM degiro_products")
        db.commit()
        logger.info(
            "Migration: added 'vwd_identifier_type' column and purged degiro_products"
        )
    except Exception:
        pass  # Column already exists, no purge needed

    logger.info("Database initialized at %s", cfg.db_path)


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    return get_db().execute(sql, params)


def fetchall(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def fetchone(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def commit():
    get_db().commit()


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
