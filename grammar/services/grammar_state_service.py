"""Grammar session state helpers."""

from grammar.enums import GrammarState
from grammar.repositories import abandon_active_sessions, get_active_session, set_session_state


def get_user_active_session(user_id: str):
    return get_active_session(user_id)


def mark_session_awaiting_answer(session_id: str) -> None:
    set_session_state(session_id, GrammarState.AWAITING_ANSWER.value)


def mark_session_showing_feedback(session_id: str) -> None:
    set_session_state(session_id, GrammarState.SHOWING_FEEDBACK.value)


def abandon_user_sessions(user_id: str) -> None:
    abandon_active_sessions(user_id)
