"""Exercise selection and session creation."""

from __future__ import annotations

import random

from grammar.content_loader import get_exercise_by_id, get_topic_exercises
from grammar.dto import ExerciseDTO
from grammar.enums import GrammarState, SessionMode
from grammar.repositories import create_session, get_session


def _pick_items(pool: list[ExerciseDTO], count: int, prefer_harder: bool = False) -> list[ExerciseDTO]:
    if not pool or count <= 0:
        return []
    items = list(pool)
    if prefer_harder:
        items.sort(key=lambda item: (item.difficulty, item.exercise_id), reverse=True)
        items = items[: max(count * 2, count)]
    if len(items) <= count:
        return items
    return random.sample(items, count)


def _selection_profile(level: str) -> tuple[dict[str, int], dict[str, int]]:
    level = (level or "").upper()
    if level in {"B2", "C1"}:
        return (
            {"multiple_choice": 2, "fill_in_the_gap": 2, "sentence_transformation": 3},
            {"sentence_transformation": 0, "fill_in_the_gap": 1, "multiple_choice": 2},
        )
    if level == "B1":
        return (
            {"multiple_choice": 3, "fill_in_the_gap": 2, "sentence_transformation": 2},
            {"multiple_choice": 0, "fill_in_the_gap": 1, "sentence_transformation": 2},
        )
    return (
        {"multiple_choice": 4, "fill_in_the_gap": 2, "sentence_transformation": 1},
        {"multiple_choice": 0, "fill_in_the_gap": 1, "sentence_transformation": 2},
    )


def _select_topic_practice_items(exercises: list[ExerciseDTO], level: str, size: int = 7) -> list[ExerciseDTO]:
    multiple_choice = [item for item in exercises if item.type.value == "multiple_choice"]
    fill_in_gap = [item for item in exercises if item.type.value == "fill_in_the_gap"]
    transformations = [item for item in exercises if item.type.value == "sentence_transformation"]
    counts, type_priority = _selection_profile(level)
    prefer_harder = level.upper() in {"B2", "C1"}

    selected: list[ExerciseDTO] = []
    selected.extend(_pick_items(multiple_choice, min(counts["multiple_choice"], len(multiple_choice)), prefer_harder))
    selected.extend(_pick_items(fill_in_gap, min(counts["fill_in_the_gap"], len(fill_in_gap)), prefer_harder))
    selected.extend(_pick_items(transformations, min(counts["sentence_transformation"], len(transformations)), True))

    if len(selected) < size:
        pool = [item for item in exercises if item not in selected]
        pool.sort(key=lambda item: (item.difficulty, item.exercise_id), reverse=prefer_harder)
        if len(pool) > size - len(selected):
            extra = random.sample(pool[: max((size - len(selected)) * 2, size - len(selected))], size - len(selected))
        else:
            extra = pool
        selected.extend(extra)

    selected = selected[:size]
    selected.sort(key=lambda item: (type_priority[item.type.value], item.difficulty, item.exercise_id))
    return selected


def _session_queue_from_exercises(exercises: list[ExerciseDTO]) -> list[dict]:
    return [
        {"topic_id": exercise.topic_id, "exercise_id": exercise.exercise_id}
        for exercise in exercises
    ]


def create_topic_session(user_id: str, chat_id: str, level: str, topic_id: str):
    exercises = _select_topic_practice_items(get_topic_exercises(topic_id), level=level, size=7)
    return create_session(
        user_id=user_id,
        chat_id=chat_id,
        level=level,
        topic_id=topic_id,
        mode=SessionMode.TOPIC_PRACTICE.value,
        state=GrammarState.AWAITING_ANSWER.value,
        exercise_queue=_session_queue_from_exercises(exercises),
    )


def create_review_session(user_id: str, chat_id: str, level: str, mode: SessionMode, exercises: list[ExerciseDTO]):
    queue = _session_queue_from_exercises(exercises[:5])
    return create_session(
        user_id=user_id,
        chat_id=chat_id,
        level=level,
        topic_id=None,
        mode=mode.value,
        state=GrammarState.REVIEW_SESSION.value,
        exercise_queue=queue,
    )


def get_current_exercise(session_id: str) -> ExerciseDTO | None:
    session = get_session(session_id)
    if not session:
        return None
    if session.current_exercise_index >= len(session.exercise_queue_json):
        return None
    current = session.exercise_queue_json[session.current_exercise_index]
    return get_exercise_by_id(current["exercise_id"])
