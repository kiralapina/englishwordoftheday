"""Pydantic DTOs for the grammar module."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from grammar.enums import ExerciseType, GrammarAction, GrammarState, SessionMode, TopicStatus


class GrammarButtonDTO(BaseModel):
    text: str
    callback_data: str | None = None


class GrammarResponseDTO(BaseModel):
    message_text: str
    buttons: list[list[GrammarButtonDTO]] = Field(default_factory=list)
    parse_mode: str = "HTML"
    expects_text_reply: bool = False
    state_update: dict[str, Any] = Field(default_factory=dict)
    side_effects: dict[str, Any] = Field(default_factory=dict)


class GrammarEventDTO(BaseModel):
    user_id: str
    chat_id: str
    level: str
    ui_language: str = "ru"
    action: GrammarAction
    topic_id: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GrammarTopicDTO(BaseModel):
    topic_id: str
    level: str
    title: str
    order: int
    is_active: bool = True
    status: TopicStatus = TopicStatus.NEW
    mastery_score: int = 0
    is_available: bool = True


class TheoryDTO(BaseModel):
    topic_id: str
    title: str
    summary: str
    structure: list[str]
    examples: list[str]
    common_mistakes: list[str]


class ExerciseDTO(BaseModel):
    exercise_id: str
    topic_id: str
    level: str
    type: ExerciseType
    prompt: str
    options: list[str] = Field(default_factory=list)
    source_sentence: str | None = None
    instruction: str | None = None
    correct_answers: list[str]
    accepted_answers: list[str]
    explanation_template: str | None = None
    mistake_type: str
    difficulty: int = 1
    llm_check_allowed: bool = False
    is_active: bool = True


class CheckResultDTO(BaseModel):
    is_correct: bool = False
    check_mode: Literal["deterministic", "llm", "skipped"] = "deterministic"
    matched_answer: str | None = None
    normalized_user_answer: str = ""
    user_answer: str = ""
    reason: str = ""
    mistake_type: str | None = None
    skipped: bool = False


class GrammarSessionDTO(BaseModel):
    session_id: str
    user_id: str
    chat_id: str
    level: str
    topic_id: str | None = None
    mode: SessionMode
    state: GrammarState
    current_exercise_index: int = 0
    exercise_queue: list[dict[str, Any]]
    correct_answers_count: int = 0
    wrong_answers_count: int = 0


class TopicProgressDTO(BaseModel):
    user_id: str
    topic_id: str
    attempts_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    mastery_score: int = 0
    status: TopicStatus = TopicStatus.NEW


class GrammarSummaryDTO(BaseModel):
    topic_title: str
    topic_status: TopicStatus
    mastery_score: int
    correct_answers_count: int
    wrong_answers_count: int
