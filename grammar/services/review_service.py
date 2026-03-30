"""Review session builders."""

from __future__ import annotations

from grammar.content_loader import get_exercise_by_id, get_topic_exercises
from grammar.dto import ExerciseDTO
from grammar.enums import SessionMode
from grammar.repositories import get_recent_mistakes, get_weak_topic_ids
from grammar.services.exercise_service import create_review_session


def create_weak_topics_review_session(user_id: str, chat_id: str, level: str):
    exercises: list[ExerciseDTO] = []
    for topic_id in get_weak_topic_ids(user_id, limit=5):
        topic_exercises = get_topic_exercises(topic_id)
        for exercise in topic_exercises:
            exercises.append(exercise)
            if len(exercises) >= 5:
                break
        if len(exercises) >= 5:
            break
    return create_review_session(user_id, chat_id, level, SessionMode.WEAK_TOPICS_REVIEW, exercises)


def create_mistakes_review_session(user_id: str, chat_id: str, level: str):
    seen: set[str] = set()
    exercises: list[ExerciseDTO] = []
    fallback_topics: list[str] = []
    for row in get_recent_mistakes(user_id, limit=20):
        exercise_id = row["exercise_id"]
        fallback_topics.append(row["topic_id"])
        if exercise_id in seen:
            continue
        seen.add(exercise_id)
        exercises.append(get_exercise_by_id(exercise_id))
        if len(exercises) >= 5:
            break
    if len(exercises) < 5:
        for topic_id in fallback_topics:
            for exercise in get_topic_exercises(topic_id):
                if exercise.exercise_id in seen:
                    continue
                seen.add(exercise.exercise_id)
                exercises.append(exercise)
                if len(exercises) >= 5:
                    break
            if len(exercises) >= 5:
                break
    return create_review_session(user_id, chat_id, level, SessionMode.MISTAKES_REVIEW, exercises)
