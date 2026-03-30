"""Load and validate local grammar content."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import orjson

from grammar.dto import ExerciseDTO, GrammarTopicDTO, TheoryDTO


class GrammarContentError(RuntimeError):
    """Raised when grammar content is missing or invalid."""


CONTENT_ROOT = Path(__file__).resolve().parents[1] / "content" / "grammar"
TOPICS_ROOT = CONTENT_ROOT / "topics"
THEORY_ROOT = CONTENT_ROOT / "theory"
EXERCISES_ROOT = CONTENT_ROOT / "exercises"


def _read_json(path: Path) -> object:
    if not path.exists():
        raise GrammarContentError(f"Grammar content file not found: {path}")
    return orjson.loads(path.read_bytes())


@lru_cache(maxsize=8)
def get_topics_for_level(level: str) -> list[GrammarTopicDTO]:
    payload = _read_json(TOPICS_ROOT / f"{level.lower()}.json")
    if not isinstance(payload, list):
        raise GrammarContentError(f"Invalid topics payload for level {level}")
    return [GrammarTopicDTO.model_validate(item) for item in sorted(payload, key=lambda item: item["order"])]


@lru_cache(maxsize=32)
def get_topic_theory(topic_id: str) -> TheoryDTO:
    payload = _read_json(THEORY_ROOT / f"{topic_id}.json")
    if not isinstance(payload, dict):
        raise GrammarContentError(f"Invalid theory payload for topic {topic_id}")
    return TheoryDTO.model_validate(payload)


@lru_cache(maxsize=64)
def get_topic_exercises(topic_id: str) -> list[ExerciseDTO]:
    payload = _read_json(EXERCISES_ROOT / f"{topic_id}.json")
    if not isinstance(payload, list):
        raise GrammarContentError(f"Invalid exercises payload for topic {topic_id}")
    return [ExerciseDTO.model_validate(item) for item in payload if item.get("is_active", True)]


@lru_cache(maxsize=1)
def get_all_topics() -> list[GrammarTopicDTO]:
    topics: list[GrammarTopicDTO] = []
    for level in ("a1", "a2", "b1", "b2", "c1"):
        topics.extend(get_topics_for_level(level))
    return sorted(topics, key=lambda topic: (topic.level, topic.order))


@lru_cache(maxsize=1)
def get_all_exercises() -> list[ExerciseDTO]:
    exercises: list[ExerciseDTO] = []
    for topic in get_all_topics():
        exercises.extend(get_topic_exercises(topic.topic_id))
    return exercises


@lru_cache(maxsize=1)
def _exercise_index() -> dict[str, ExerciseDTO]:
    return {exercise.exercise_id: exercise for exercise in get_all_exercises()}


def get_exercise_by_id(exercise_id: str) -> ExerciseDTO:
    exercise = _exercise_index().get(exercise_id)
    if not exercise:
        raise GrammarContentError(f"Exercise not found: {exercise_id}")
    return exercise


def validate_content_store() -> dict[str, int]:
    topic_count = len(get_all_topics())
    exercise_count = len(get_all_exercises())
    theory_count = 0
    for topic in get_all_topics():
        get_topic_theory(topic.topic_id)
        theory_count += 1
    return {
        "topics": topic_count,
        "theory_files": theory_count,
        "exercises": exercise_count,
    }
