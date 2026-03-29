"""Independent bot-wide usage metrics and MAU calculation."""

import logging
from datetime import datetime, timedelta

import database

logger = logging.getLogger(__name__)


def init_usage_metrics() -> None:
    """Create analytics tables and indexes if they do not exist."""
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_activity_log (
                    id BIGSERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    event_type VARCHAR(100) NOT NULL,
                    event_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_event_at
                ON user_activity_log(event_at);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_user_event_at
                ON user_activity_log(user_id, event_at);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_activity_event_type_event_at
                ON user_activity_log(event_type, event_at);
                """
            )


def track_user_activity(user_id: str, event_type: str, event_at: datetime) -> None:
    """Persist a single user activity event for analytics."""
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_activity_log (user_id, event_type, event_at, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (str(user_id), event_type.strip(), event_at, datetime.utcnow()),
            )


def get_monthly_active_users(days: int = 30) -> int:
    """Count distinct users active in the rolling time window."""
    window_start = datetime.utcnow() - timedelta(days=days)
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT user_id) AS mau
                FROM user_activity_log
                WHERE event_at >= %s
                """,
                (window_start,),
            )
            row = cur.fetchone()
            return int(row["mau"]) if row and row["mau"] is not None else 0


def get_usage_metrics(days: int = 30) -> dict:
    """Return a compact analytics payload for internal stats views."""
    calculated_at = datetime.utcnow()
    return {
        "mau": get_monthly_active_users(days=days),
        "window_days": days,
        "calculated_at": calculated_at.isoformat(timespec="seconds") + "Z",
    }
