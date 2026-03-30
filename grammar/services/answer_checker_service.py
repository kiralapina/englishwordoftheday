"""Deterministic and optional LLM-backed answer checking."""

from __future__ import annotations

import re
import string

from grammar.dto import CheckResultDTO, ExerciseDTO
from grammar.enums import ExerciseType
from grammar.llm.transformation_checker import check_transformation_equivalence


def normalize_answer(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("\u2019", "'").replace("`", "'")
    text = re.sub(r"\s+", " ", text)
    text = text.rstrip(string.punctuation + " ")
    return text


_CONTRACTIONS = {
    "i'm": "i am", "you're": "you are", "he's": "he is", "she's": "she is",
    "it's": "it is", "we're": "we are", "they're": "they are",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not",
    "weren't": "were not", "don't": "do not", "doesn't": "does not",
    "didn't": "did not", "won't": "will not", "wouldn't": "would not",
    "shouldn't": "should not", "couldn't": "could not", "can't": "cannot",
    "hasn't": "has not", "haven't": "have not", "hadn't": "had not",
}


def _expand_contractions(text: str) -> str:
    for short, full in _CONTRACTIONS.items():
        text = text.replace(short, full)
    return text


def _fuzzy_match(user: str, accepted: list[str]) -> bool:
    """Lenient comparison: expand contractions, ignore trailing punctuation."""
    user_expanded = _expand_contractions(user)
    for ans in accepted:
        if user_expanded == _expand_contractions(ans):
            return True
    return False


def check_answer(exercise: ExerciseDTO, user_answer: str) -> CheckResultDTO:
    normalized = normalize_answer(user_answer)
    accepted = [normalize_answer(answer) for answer in exercise.accepted_answers]
    correct = [normalize_answer(answer) for answer in exercise.correct_answers]

    if exercise.type == ExerciseType.MULTIPLE_CHOICE:
        is_correct = normalized in correct
        return CheckResultDTO(
            is_correct=is_correct,
            check_mode="deterministic",
            matched_answer=normalized if is_correct else None,
            normalized_user_answer=normalized,
            user_answer=user_answer,
            mistake_type=None if is_correct else exercise.mistake_type,
        )

    if exercise.type == ExerciseType.FILL_IN_THE_GAP:
        is_correct = normalized in accepted or _fuzzy_match(normalized, accepted)
        return CheckResultDTO(
            is_correct=is_correct,
            check_mode="deterministic",
            matched_answer=normalized if is_correct else None,
            normalized_user_answer=normalized,
            user_answer=user_answer,
            mistake_type=None if is_correct else exercise.mistake_type,
        )

    # sentence_transformation and any other text types
    if normalized in accepted or _fuzzy_match(normalized, accepted):
        return CheckResultDTO(
            is_correct=True,
            check_mode="deterministic",
            matched_answer=normalized,
            normalized_user_answer=normalized,
            user_answer=user_answer,
        )

    # Try optional LLM if allowed and configured
    if exercise.llm_check_allowed:
        llm_result = check_transformation_equivalence(
            source_sentence=exercise.source_sentence or "",
            instruction=exercise.instruction or "",
            accepted_answers=exercise.accepted_answers,
            user_answer=user_answer,
        )
        if llm_result is not None:
            return CheckResultDTO(
                is_correct=bool(llm_result.get("is_correct")),
                check_mode="llm",
                matched_answer=normalized if llm_result.get("is_correct") else None,
                normalized_user_answer=normalized,
                user_answer=user_answer,
                reason=str(llm_result.get("reason", "")),
                mistake_type=None if llm_result.get("is_correct") else exercise.mistake_type,
            )

    # Deterministic fallback: answer doesn't match any accepted variant
    return CheckResultDTO(
        is_correct=False,
        check_mode="deterministic",
        matched_answer=None,
        normalized_user_answer=normalized,
        user_answer=user_answer,
        mistake_type=exercise.mistake_type,
    )
