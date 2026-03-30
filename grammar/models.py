"""Internal row models for the grammar module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GrammarSessionRecord(BaseModel):
    session_id: str
    user_id: str
    chat_id: str
    level: str
    topic_id: str | None = None
    mode: str
    state: str
    current_exercise_index: int = 0
    exercise_queue_json: list[dict[str, Any]] = Field(default_factory=list)
    correct_answers_count: int = 0
    wrong_answers_count: int = 0
    started_at: datetime
    completed_at: datetime | None = None
    abandoned_at: datetime | None = None
    updated_at: datetime


class TopicProgressRecord(BaseModel):
    user_id: str
    topic_id: str
    attempts_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    mastery_score: int = 0
    status: str = "new"
    last_practiced_at: datetime | None = None


class GrammarMistakeRecord(BaseModel):
    user_id: str
    topic_id: str
    exercise_id: str
    mistake_type: str | None = None
    user_answer: str | None = None
    correct_answer: str | None = None
    is_repeated: bool = False
    created_at: datetime
