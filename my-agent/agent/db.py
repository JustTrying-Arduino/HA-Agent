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
            duration_ms INTEGER NOT NULL
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

        CREATE TABLE IF NOT EXISTS market_eod_prices (
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            date TEXT NOT NULL,
            name TEXT,
            currency TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY(symbol, exchange, date)
        );

        CREATE INDEX IF NOT EXISTS idx_market_eod_symbol_exchange_date
            ON market_eod_prices(symbol, exchange, date DESC);

        CREATE TABLE IF NOT EXISTS market_api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            request_kind TEXT NOT NULL,
            exchange TEXT,
            symbols TEXT NOT NULL,
            symbols_count INTEGER NOT NULL,
            status TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            note TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_market_api_usage_timestamp
            ON market_api_usage(timestamp);
    """)
    db.commit()

    # Migrations
    try:
        db.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        db.commit()
        logger.info("Migration: added 'model' column to messages table")
    except Exception:
        pass  # Column already exists

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
