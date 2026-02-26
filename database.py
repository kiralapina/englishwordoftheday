# -*- coding: utf-8 -*-
"""PostgreSQL-база для пользователей и лексики (alwaysdata / любой PostgreSQL)."""
import os
from contextlib import contextmanager
from datetime import date, timedelta
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

# Интервалы SRS (дней до следующего повторения по этапам)
SRS_INTERVALS = [1, 3, 7, 14, 30]  # этапы 1-5


def _get_connection_params() -> dict:
    """Параметры подключения из переменных окружения (alwaysdata и др.)."""
    # Если заданы отдельные переменные — используем их (удобно для пароля без спецсимволов в URL)
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
    # Fallback на отдельные переменные
    return {
        "host": os.getenv("PGHOST", "localhost"),
        "port": int(os.getenv("PGPORT", "5432")),
        "dbname": os.getenv("PGDATABASE", "lingvo_bot"),
        "user": os.getenv("PGUSER", ""),
        "password": os.getenv("PGPASSWORD", ""),
    }


@contextmanager
def get_connection():
    params = _get_connection_params()
    if "dsn" in params:
        conn = psycopg2.connect(params["dsn"], cursor_factory=RealDictCursor)
    else:
        if (params.get("host") == "localhost" or not params.get("host")) and not params.get("password"):
            raise ValueError(
                "Не заданы параметры БД. Добавьте в .env:\n"
                "PGHOST=postgresql-ВАШ_ЛОГИН.alwaysdata.net\n"
                "PGPORT=5432\n"
                "PGDATABASE=superwomansocool_test\n"
                "PGUSER=superwomansocool\n"
                "PGPASSWORD=ваш_пароль"
            )
        conn = psycopg2.connect(**params, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
                    daily_goal INTEGER DEFAULT 5,
                    created_at DATE DEFAULT CURRENT_DATE
                );
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
