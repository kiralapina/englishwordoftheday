# -*- coding: utf-8 -*-
"""PostgreSQL-база для пользователей и лексики (alwaysdata / любой PostgreSQL)."""
import logging
import os
from contextlib import contextmanager
from datetime import date, timedelta
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool as _pg_pool

logger = logging.getLogger(__name__)

# Интервалы SRS (дней до следующего повторения по этапам)
SRS_INTERVALS = [1, 3, 7, 14, 30]  # этапы 1-5

_connection_pool: _pg_pool.ThreadedConnectionPool | None = None


def _get_connection_params() -> dict:
    """Параметры подключения из переменных окружения (alwaysdata и др.)."""
    if os.getenv("PGHOST"):
        return {
            "host": os.getenv("PGHOST"),
            "port": int(os.getenv("PGPORT", "5432")),
            "dbname": os.getenv("PGDATABASE", "lingvo_bot"),
            "user": os.getenv("PGUSER", ""),
            "password": os.getenv("PGPASSWORD", ""),
        }
    url = os.getenv("DATABASE_URL")
    if url and "SERVER" not in url and "PASSWORD" not in url:
        if url.startswith("postgres://"):
            url = "postgresql://" + url.split("://", 1)[1]
        return {"dsn": url}
    return {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "lingvo_bot"),
        "user": os.getenv("PGUSER", ""),
        "password": os.getenv("PGPASSWORD", ""),
    }


def _ensure_pool() -> _pg_pool.ThreadedConnectionPool:
    global _connection_pool
    if _connection_pool is not None and not _connection_pool.closed:
        return _connection_pool
    params = _get_connection_params()
    if "dsn" not in params:
        if (params.get("host") == "localhost" or not params.get("host")) and not params.get("password"):
            raise ValueError(
                "Не заданы параметры БД. Добавьте в .env:\n"
                "PGHOST=postgresql-ВАШ_ЛОГИН.alwaysdata.net\n"
                "PGPORT=5432\n"
                "PGDATABASE=superwomansocool_test\n"
                "PGUSER=superwomansocool\n"
                "PGPASSWORD=ваш_пароль"
            )
    if "dsn" in params:
        _connection_pool = _pg_pool.ThreadedConnectionPool(
            minconn=1, maxconn=8, dsn=params["dsn"], cursor_factory=RealDictCursor,
        )
    else:
        _connection_pool = _pg_pool.ThreadedConnectionPool(
            minconn=1, maxconn=8, cursor_factory=RealDictCursor, **params,
        )
    logger.info("DB connection pool created (1–8 connections)")
    return _connection_pool


@contextmanager
def get_connection():
    p = _ensure_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


_ADVISORY_LOCK_ID = 73917149  # derived from bot token prefix, arbitrary unique int


def try_acquire_bot_lock() -> bool:
    """Try to acquire a PostgreSQL session-level advisory lock.

    Returns True if this is the only running instance. The lock is held for the
    lifetime of the connection, which the caller must keep open.
    """
    _ensure_pool()
    try:
        conn = _ensure_pool().getconn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s) AS ok", (_ADVISORY_LOCK_ID,))
            row = cur.fetchone()
            acquired = bool(row and row["ok"])
        if not acquired:
            _ensure_pool().putconn(conn)
        # If acquired, intentionally do NOT return the connection to the pool —
        # the advisory lock stays held for as long as this connection is alive.
        return acquired
    except Exception as e:
        logger.error("Failed to acquire advisory lock: %s", e)
        return False


def init_db() -> None:
    """Создание таблиц users и vocabulary, если их нет (совместимо с alwaysdata)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    target_language TEXT DEFAULT 'English',
                    level TEXT DEFAULT 'B1',
                    grammar_notifications_enabled BOOLEAN DEFAULT FALSE,
                    daily_goal INTEGER DEFAULT 5,
                    created_at DATE DEFAULT CURRENT_DATE
                );
            """)
            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS grammar_notifications_enabled BOOLEAN DEFAULT FALSE;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS vocabulary (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    word TEXT NOT NULL,
                    translation TEXT,
                    transcription TEXT,
                    example_sentence TEXT,
                    srs_stage INTEGER DEFAULT 1,
                    next_review DATE DEFAULT CURRENT_DATE,
                    created_at DATE DEFAULT CURRENT_DATE
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_vocab_user_review
                ON vocabulary(user_id, next_review);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_vocabulary_user_id
                ON vocabulary(user_id);
            """)


def init_grammar_db() -> None:
    """Создание таблиц grammar-модуля."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS grammar_topics (
                    id BIGSERIAL PRIMARY KEY,
                    topic_id VARCHAR(255) NOT NULL UNIQUE,
                    level VARCHAR(10) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    sort_order INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS grammar_exercises (
                    id BIGSERIAL PRIMARY KEY,
                    exercise_id VARCHAR(255) NOT NULL UNIQUE,
                    topic_id VARCHAR(255) NOT NULL,
                    level VARCHAR(10) NOT NULL,
                    type VARCHAR(50) NOT NULL,
                    prompt TEXT NOT NULL,
                    payload_json JSONB NOT NULL,
                    correct_answers_json JSONB NOT NULL,
                    accepted_answers_json JSONB NOT NULL,
                    explanation_template TEXT,
                    mistake_type VARCHAR(255),
                    difficulty INTEGER NOT NULL DEFAULT 1,
                    llm_check_allowed BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_grammar_topic_progress (
                    id BIGSERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    topic_id VARCHAR(255) NOT NULL,
                    attempts_count INTEGER NOT NULL DEFAULT 0,
                    correct_count INTEGER NOT NULL DEFAULT 0,
                    wrong_count INTEGER NOT NULL DEFAULT 0,
                    mastery_score INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR(50) NOT NULL DEFAULT 'new',
                    last_practiced_at TIMESTAMP NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, topic_id)
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_grammar_topic_progress_user_status
                ON user_grammar_topic_progress(user_id, status);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_grammar_mistakes (
                    id BIGSERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    topic_id VARCHAR(255) NOT NULL,
                    exercise_id VARCHAR(255) NOT NULL,
                    mistake_type VARCHAR(255),
                    user_answer TEXT,
                    correct_answer TEXT,
                    is_repeated BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_grammar_mistakes_topic
                ON user_grammar_mistakes(user_id, topic_id);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_grammar_mistakes_created_at
                ON user_grammar_mistakes(user_id, created_at);
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS grammar_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    session_id UUID NOT NULL UNIQUE,
                    user_id VARCHAR(255) NOT NULL,
                    chat_id VARCHAR(255) NOT NULL,
                    level VARCHAR(10) NOT NULL,
                    topic_id VARCHAR(255),
                    mode VARCHAR(50) NOT NULL,
                    state VARCHAR(50) NOT NULL,
                    current_exercise_index INTEGER NOT NULL DEFAULT 0,
                    exercise_queue_json JSONB NOT NULL,
                    correct_answers_count INTEGER NOT NULL DEFAULT 0,
                    wrong_answers_count INTEGER NOT NULL DEFAULT 0,
                    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMP NULL,
                    abandoned_at TIMESTAMP NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_grammar_sessions_user_state
                ON grammar_sessions(user_id, state);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_grammar_sessions_user_started_at
                ON grammar_sessions(user_id, started_at);
            """)


def get_or_create_user(user_id: int, username: Optional[str] = None) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, username, level, daily_goal FROM users WHERE user_id = %s",
                (user_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            cur.execute(
                "INSERT INTO users (user_id, username, level) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING",
                (user_id, username or "", "B1")
            )
            return {"user_id": user_id, "username": username, "level": "B1", "daily_goal": 5}


def set_user_level(user_id: int, level: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET level = %s WHERE user_id = %s", (level, user_id))


def get_user_level(user_id: int) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT level FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row["level"] if row else "B1"


def set_grammar_notifications_enabled(user_id: int, enabled: bool) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, grammar_notifications_enabled)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE
                SET grammar_notifications_enabled = EXCLUDED.grammar_notifications_enabled
                """,
                (user_id, enabled),
            )


def get_grammar_notifications_enabled(user_id: int) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT grammar_notifications_enabled FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return bool(row["grammar_notifications_enabled"]) if row else False


def get_users_with_grammar_notifications() -> List[int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id
                FROM users
                WHERE grammar_notifications_enabled = TRUE
                """
            )
            return [row["user_id"] for row in cur.fetchall()]


def add_word(user_id: int, word: str, translation: str = "", transcription: str = "", example: str = "") -> Optional[int]:
    today = date.today().isoformat()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO vocabulary (user_id, word, translation, transcription, example_sentence, srs_stage, next_review)
                   VALUES (%s, %s, %s, %s, %s, 1, %s)
                   RETURNING id""",
                (user_id, word.strip(), (translation or "").strip(), (transcription or "").strip(), (example or "").strip(), today)
            )
            row = cur.fetchone()
            return row["id"] if row else None


def get_words_for_review(user_id: int, limit: int = 10) -> List[dict]:
    today = date.today().isoformat()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, word, translation, transcription, example_sentence, srs_stage
                   FROM vocabulary WHERE user_id = %s AND next_review <= %s
                   ORDER BY next_review LIMIT %s""",
                (user_id, today, limit)
            )
            return [dict(r) for r in cur.fetchall()]


def advance_srs(vocab_id: int, user_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT srs_stage FROM vocabulary WHERE id = %s AND user_id = %s",
                (vocab_id, user_id)
            )
            row = cur.fetchone()
            if not row:
                return
            stage = min(row["srs_stage"] + 1, len(SRS_INTERVALS))
            days = SRS_INTERVALS[stage - 1]
            next_date = (date.today() + timedelta(days=days)).isoformat()
            cur.execute(
                "UPDATE vocabulary SET srs_stage = %s, next_review = %s WHERE id = %s AND user_id = %s",
                (stage, next_date, vocab_id, user_id)
            )


def get_all_user_words(user_id: int, limit: int = 50) -> List[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, word, translation, transcription, example_sentence, next_review
                   FROM vocabulary WHERE user_id = %s ORDER BY created_at DESC LIMIT %s""",
                (user_id, limit)
            )
            return [dict(r) for r in cur.fetchall()]


def get_all_user_ids() -> List[int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [r["user_id"] for r in cur.fetchall()]
