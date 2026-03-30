"""Repositories for grammar module persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from psycopg2.extras import Json

import database
from grammar.dto import ExerciseDTO, GrammarSessionDTO, GrammarTopicDTO
from grammar.models import GrammarSessionRecord, TopicProgressRecord


def sync_catalog(topics: list[GrammarTopicDTO], exercises: list[ExerciseDTO]) -> None:
    """Upsert local grammar content into DB catalog tables."""
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            for topic in topics:
                cur.execute(
                    """
                    INSERT INTO grammar_topics (topic_id, level, title, sort_order, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (topic_id) DO UPDATE
                    SET level = EXCLUDED.level,
                        title = EXCLUDED.title,
                        sort_order = EXCLUDED.sort_order,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    (topic.topic_id, topic.level, topic.title, topic.order, topic.is_active),
                )
            for exercise in exercises:
                payload = {
                    "options": exercise.options,
                    "source_sentence": exercise.source_sentence,
                    "instruction": exercise.instruction,
                }
                cur.execute(
                    """
                    INSERT INTO grammar_exercises (
                        exercise_id, topic_id, level, type, prompt, payload_json,
                        correct_answers_json, accepted_answers_json, explanation_template,
                        mistake_type, difficulty, llm_check_allowed, is_active, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (exercise_id) DO UPDATE
                    SET topic_id = EXCLUDED.topic_id,
                        level = EXCLUDED.level,
                        type = EXCLUDED.type,
                        prompt = EXCLUDED.prompt,
                        payload_json = EXCLUDED.payload_json,
                        correct_answers_json = EXCLUDED.correct_answers_json,
                        accepted_answers_json = EXCLUDED.accepted_answers_json,
                        explanation_template = EXCLUDED.explanation_template,
                        mistake_type = EXCLUDED.mistake_type,
                        difficulty = EXCLUDED.difficulty,
                        llm_check_allowed = EXCLUDED.llm_check_allowed,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    (
                        exercise.exercise_id,
                        exercise.topic_id,
                        exercise.level,
                        exercise.type.value,
                        exercise.prompt,
                        Json(payload),
                        Json(exercise.correct_answers),
                        Json(exercise.accepted_answers),
                        exercise.explanation_template,
                        exercise.mistake_type,
                        exercise.difficulty,
                        exercise.llm_check_allowed,
                        exercise.is_active,
                    ),
                )


def abandon_active_sessions(user_id: str) -> None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE grammar_sessions
                SET state = 'grammar_completed',
                    abandoned_at = NOW(),
                    updated_at = NOW()
                WHERE user_id = %s
                  AND completed_at IS NULL
                  AND abandoned_at IS NULL
                """,
                (str(user_id),),
            )


def create_session(
    user_id: str,
    chat_id: str,
    level: str,
    topic_id: str | None,
    mode: str,
    state: str,
    exercise_queue: list[dict],
) -> GrammarSessionRecord:
    session_id = str(uuid4())
    abandon_active_sessions(user_id)
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO grammar_sessions (
                    session_id, user_id, chat_id, level, topic_id, mode, state,
                    current_exercise_index, exercise_queue_json, correct_answers_count,
                    wrong_answers_count, started_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, 0, 0, NOW(), NOW())
                RETURNING session_id, user_id, chat_id, level, topic_id, mode, state,
                          current_exercise_index, exercise_queue_json, correct_answers_count,
                          wrong_answers_count, started_at, completed_at, abandoned_at, updated_at
                """,
                (session_id, str(user_id), str(chat_id), level, topic_id, mode, state, Json(exercise_queue)),
            )
            row = cur.fetchone()
            return GrammarSessionRecord.model_validate(dict(row))


def get_session(session_id: str) -> GrammarSessionRecord | None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, user_id, chat_id, level, topic_id, mode, state,
                       current_exercise_index, exercise_queue_json, correct_answers_count,
                       wrong_answers_count, started_at, completed_at, abandoned_at, updated_at
                FROM grammar_sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
            return GrammarSessionRecord.model_validate(dict(row)) if row else None


def get_active_session(user_id: str) -> GrammarSessionRecord | None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, user_id, chat_id, level, topic_id, mode, state,
                       current_exercise_index, exercise_queue_json, correct_answers_count,
                       wrong_answers_count, started_at, completed_at, abandoned_at, updated_at
                FROM grammar_sessions
                WHERE user_id = %s
                  AND completed_at IS NULL
                  AND abandoned_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (str(user_id),),
            )
            row = cur.fetchone()
            return GrammarSessionRecord.model_validate(dict(row)) if row else None


def update_session_progress(session_id: str, is_correct: bool) -> GrammarSessionRecord:
    field = "correct_answers_count" if is_correct else "wrong_answers_count"
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE grammar_sessions
                SET current_exercise_index = current_exercise_index + 1,
                    {field} = {field} + 1,
                    state = 'showing_feedback',
                    updated_at = NOW()
                WHERE session_id = %s
                RETURNING session_id, user_id, chat_id, level, topic_id, mode, state,
                          current_exercise_index, exercise_queue_json, correct_answers_count,
                          wrong_answers_count, started_at, completed_at, abandoned_at, updated_at
                """,
                (session_id,),
            )
            row = cur.fetchone()
            return GrammarSessionRecord.model_validate(dict(row))


def advance_after_skip(session_id: str) -> GrammarSessionRecord:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE grammar_sessions
                SET current_exercise_index = current_exercise_index + 1,
                    state = 'showing_feedback',
                    updated_at = NOW()
                WHERE session_id = %s
                RETURNING session_id, user_id, chat_id, level, topic_id, mode, state,
                          current_exercise_index, exercise_queue_json, correct_answers_count,
                          wrong_answers_count, started_at, completed_at, abandoned_at, updated_at
                """,
                (session_id,),
            )
            row = cur.fetchone()
            return GrammarSessionRecord.model_validate(dict(row))


def set_session_state(session_id: str, state: str) -> None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE grammar_sessions SET state = %s, updated_at = NOW() WHERE session_id = %s",
                (state, session_id),
            )


def complete_session(session_id: str) -> GrammarSessionRecord:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE grammar_sessions
                SET state = 'grammar_completed',
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE session_id = %s
                RETURNING session_id, user_id, chat_id, level, topic_id, mode, state,
                          current_exercise_index, exercise_queue_json, correct_answers_count,
                          wrong_answers_count, started_at, completed_at, abandoned_at, updated_at
                """,
                (session_id,),
            )
            row = cur.fetchone()
            return GrammarSessionRecord.model_validate(dict(row))


def get_topic_progress(user_id: str, topic_id: str) -> TopicProgressRecord | None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, topic_id, attempts_count, correct_count, wrong_count,
                       mastery_score, status, last_practiced_at
                FROM user_grammar_topic_progress
                WHERE user_id = %s AND topic_id = %s
                """,
                (str(user_id), topic_id),
            )
            row = cur.fetchone()
            return TopicProgressRecord.model_validate(dict(row)) if row else None


def list_topic_progress(user_id: str) -> dict[str, TopicProgressRecord]:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, topic_id, attempts_count, correct_count, wrong_count,
                       mastery_score, status, last_practiced_at
                FROM user_grammar_topic_progress
                WHERE user_id = %s
                """,
                (str(user_id),),
            )
            rows = cur.fetchall()
            return {
                row["topic_id"]: TopicProgressRecord.model_validate(dict(row))
                for row in rows
            }


def upsert_topic_progress(
    user_id: str,
    topic_id: str,
    is_correct: bool,
    mastery_score: int,
    status: str,
) -> None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_grammar_topic_progress (
                    user_id, topic_id, attempts_count, correct_count, wrong_count,
                    mastery_score, status, last_practiced_at, created_at, updated_at
                )
                VALUES (%s, %s, 1, %s, %s, %s, %s, NOW(), NOW(), NOW())
                ON CONFLICT (user_id, topic_id) DO UPDATE
                SET attempts_count = user_grammar_topic_progress.attempts_count + 1,
                    correct_count = user_grammar_topic_progress.correct_count + %s,
                    wrong_count = user_grammar_topic_progress.wrong_count + %s,
                    mastery_score = %s,
                    status = %s,
                    last_practiced_at = NOW(),
                    updated_at = NOW()
                """,
                (
                    str(user_id),
                    topic_id,
                    1 if is_correct else 0,
                    0 if is_correct else 1,
                    mastery_score,
                    status,
                    1 if is_correct else 0,
                    0 if is_correct else 1,
                    mastery_score,
                    status,
                ),
            )


def has_recent_same_mistake(user_id: str, topic_id: str, mistake_type: str | None, days: int = 30) -> bool:
    if not mistake_type:
        return False
    boundary = datetime.utcnow() - timedelta(days=days)
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM user_grammar_mistakes
                WHERE user_id = %s
                  AND topic_id = %s
                  AND mistake_type = %s
                  AND created_at >= %s
                LIMIT 1
                """,
                (str(user_id), topic_id, mistake_type, boundary),
            )
            return cur.fetchone() is not None


def record_mistake(
    user_id: str,
    topic_id: str,
    exercise_id: str,
    mistake_type: str | None,
    user_answer: str,
    correct_answer: str,
    is_repeated: bool,
) -> None:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_grammar_mistakes (
                    user_id, topic_id, exercise_id, mistake_type, user_answer,
                    correct_answer, is_repeated, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (str(user_id), topic_id, exercise_id, mistake_type, user_answer, correct_answer, is_repeated),
            )


def get_recent_mistakes(user_id: str, limit: int = 20) -> list[dict]:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, topic_id, exercise_id, mistake_type, user_answer,
                       correct_answer, is_repeated, created_at
                FROM user_grammar_mistakes
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (str(user_id), limit),
            )
            return [dict(row) for row in cur.fetchall()]


def get_weak_topic_ids(user_id: str, limit: int = 5) -> list[str]:
    with database.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT topic_id
                FROM user_grammar_topic_progress
                WHERE user_id = %s
                  AND (
                    mastery_score < 40
                    OR wrong_count > correct_count
                    OR (status != 'mastered' AND (last_practiced_at IS NULL OR last_practiced_at < NOW() - INTERVAL '14 days'))
                  )
                ORDER BY mastery_score ASC, updated_at ASC
                LIMIT %s
                """,
                (str(user_id), limit),
            )
            return [row["topic_id"] for row in cur.fetchall()]
