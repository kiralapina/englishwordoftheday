"""Progress and mistake tracking."""

from __future__ import annotations

from grammar.dto import CheckResultDTO, ExerciseDTO
from grammar.enums import TopicStatus
from grammar.repositories import (
    get_topic_progress,
    has_recent_same_mistake,
    record_mistake,
    upsert_topic_progress,
)


def calculate_mastery_score(current_score: int, is_correct: bool, repeated_error: bool) -> int:
    if is_correct:
        updated = current_score + 8
    elif repeated_error:
        updated = current_score - 8
    else:
        updated = current_score - 5
    return max(0, min(100, updated))


def resolve_topic_status(score: int) -> TopicStatus:
    if score >= 80:
        return TopicStatus.MASTERED
    if score >= 20:
        return TopicStatus.IN_PROGRESS
    return TopicStatus.NEW


def update_progress(user_id: str, topic_id: str, exercise: ExerciseDTO, check_result: CheckResultDTO) -> dict:
    progress = get_topic_progress(user_id, topic_id)
    current_score = progress.mastery_score if progress else 0
    repeated_error = False

    if not check_result.is_correct and not check_result.skipped:
        repeated_error = has_recent_same_mistake(user_id, topic_id, exercise.mistake_type)

    updated_score = calculate_mastery_score(current_score, check_result.is_correct, repeated_error)
    status = resolve_topic_status(updated_score)

    if not check_result.skipped:
        upsert_topic_progress(
            user_id=user_id,
            topic_id=topic_id,
            is_correct=check_result.is_correct,
            mastery_score=updated_score,
            status=status.value,
        )

    if not check_result.is_correct and not check_result.skipped:
        record_mistake(
            user_id=user_id,
            topic_id=topic_id,
            exercise_id=exercise.exercise_id,
            mistake_type=exercise.mistake_type,
            user_answer=check_result.user_answer,
            correct_answer=exercise.correct_answers[0] if exercise.correct_answers else "",
            is_repeated=repeated_error,
        )

    return {
        "mastery_score": updated_score,
        "status": status,
        "repeated_error": repeated_error,
    }
