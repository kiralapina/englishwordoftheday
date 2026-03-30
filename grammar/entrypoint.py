"""Entrypoint for all grammar module actions."""

from __future__ import annotations

import logging

import database
from grammar import config
from grammar.content_loader import GrammarContentError, get_all_topics
from grammar.dto import GrammarButtonDTO, GrammarEventDTO, GrammarResponseDTO
from grammar.enums import ExerciseType, GrammarAction
from grammar.repositories import (
    advance_after_skip,
    complete_session,
    get_active_session,
    get_session,
    get_topic_progress,
    set_session_state,
    update_session_progress,
)
from grammar.services.answer_checker_service import check_answer
from grammar.services.exercise_service import create_topic_session, get_current_exercise
from grammar.services.feedback_service import build_feedback
from grammar.services.grammar_state_service import abandon_user_sessions
from grammar.services.progress_service import update_progress
from grammar.services.review_service import (
    create_mistakes_review_session,
    create_weak_topics_review_session,
)
from grammar.services.theory_service import load_topic_theory
from grammar.services.topic_catalog_service import get_topics_for_user_level

logger = logging.getLogger(__name__)


def _button(text: str, callback_data: str | None = None) -> GrammarButtonDTO:
    return GrammarButtonDTO(text=text, callback_data=callback_data)


def _topic_title(topic_id: str | None) -> str:
    if not topic_id:
        return "Грамматика"
    for topic in get_all_topics():
        if topic.topic_id == topic_id:
            return topic.title
    return topic_id.replace("_", " ").title()


def _render_home(level: str, user_id: str) -> GrammarResponseDTO:
    notifications_enabled = database.get_grammar_notifications_enabled(int(user_id))
    notification_label = "🔔 Напоминания по грамматике: вкл" if notifications_enabled else "🔕 Напоминания по грамматике: выкл"
    buttons = [
        [_button("Практика", "grammar:list_topics"), _button("Теория", "grammar:list_topics")],
    ]
    if config.grammar_review_enabled():
        buttons.append([_button("Слабые темы", "grammar:weak"), _button("Повторить ошибки", "grammar:mistakes")])
    buttons.append([_button(notification_label, "grammar:toggle_push")])
    buttons.append([_button("⚙️ Выбрать уровень", "grammar:choose_level"), _button("Выйти", "grammar:exit")])
    return GrammarResponseDTO(
        message_text=(
            f"<b>Грамматика</b>\n"
            f"Уровень: <b>{level}</b>\n\n"
            "1. Выбери уровень в «Настройки», если он не подходит.\n"
            "2. Открой тему и прочитай короткую теорию.\n"
            "3. В заданиях с кнопками нажимай вариант ответа.\n"
            "4. Если кнопок нет, ответ нужно написать сообщением ниже.\n"
            "5. Можно включить отдельные напоминания по грамматике."
        ),
        buttons=buttons,
        state_update={"module": "grammar", "state": "grammar_home"},
    )


def _render_topic_list(user_id: str, level: str) -> GrammarResponseDTO:
    topics = get_topics_for_user_level(level, user_id)
    status_labels = {
        "new": "новая",
        "in_progress": "в процессе",
        "mastered": "освоена",
    }
    lines = [f"<b>Темы уровня {level}</b>", ""]
    buttons: list[list[GrammarButtonDTO]] = []
    for topic in topics:
        lines.append(
            f"• <b>{topic.title}</b> — статус: {status_labels.get(topic.status.value, topic.status.value)}, освоение: {topic.mastery_score}"
        )
        buttons.append([_button(topic.title, f"grammar:topic:{topic.topic_id}")])
    buttons.append([_button("Назад", "grammar:home")])
    return GrammarResponseDTO(
        message_text="\n".join(lines),
        buttons=buttons,
        state_update={"module": "grammar", "state": "topic_list"},
    )


def _render_theory(topic_id: str) -> GrammarResponseDTO:
    theory = load_topic_theory(topic_id)
    structure = "\n".join(f"• {item}" for item in theory.structure)
    examples = "\n".join(f"• {item}" for item in theory.examples)
    mistakes = "\n".join(f"• {item}" for item in theory.common_mistakes)
    return GrammarResponseDTO(
        message_text=(
            f"<b>{theory.title}</b>\n\n"
            f"{theory.summary}\n\n"
            f"<b>Схема</b>\n{structure}\n\n"
            f"<b>Примеры</b>\n{examples}\n\n"
            f"<b>Типичные ошибки</b>\n{mistakes}\n\n"
            "После теории нажми «Начать упражнения»."
        ),
        buttons=[
            [_button("Начать упражнения", f"grammar:practice:{topic_id}")],
            [_button("Назад к темам", "grammar:list_topics")],
        ],
        state_update={"module": "grammar", "state": "topic_theory", "topic_id": topic_id},
    )


def _render_exercise(session_id: str, exercise, index: int, total: int) -> GrammarResponseDTO:
    title = _topic_title(exercise.topic_id)
    message = [
        f"<b>{title}</b>",
        f"Задание {index + 1} из {total}",
        "",
        exercise.prompt,
    ]
    if exercise.instruction:
        message.extend(["", exercise.instruction])

    buttons: list[list[GrammarButtonDTO]] = []
    expects_text = exercise.type != ExerciseType.MULTIPLE_CHOICE
    if exercise.type == ExerciseType.MULTIPLE_CHOICE:
        for idx, option in enumerate(exercise.options):
            buttons.append([_button(option, f"grammar:answer:{session_id}:{index}:{idx}")])
    else:
        message.extend(["", "Ответ напиши обычным сообщением в чат."])
        buttons.append([_button("Пропустить", f"grammar:skip:{session_id}:{index}")])
        buttons.append([_button("Выйти из Grammar", "grammar:exit")])

    return GrammarResponseDTO(
        message_text="\n".join(message),
        buttons=buttons,
        expects_text_reply=expects_text,
        state_update={
            "module": "grammar",
            "state": "awaiting_answer",
            "session_id": session_id,
            "topic_id": exercise.topic_id,
            "exercise_id": exercise.exercise_id,
            "exercise_index": index,
        },
    )


def _render_session_summary(session, feedback: str) -> GrammarResponseDTO:
    topic_id = session.topic_id or (session.exercise_queue_json[0]["topic_id"] if session.exercise_queue_json else None)
    progress = get_topic_progress(session.user_id, topic_id) if topic_id else None
    status = progress.status if progress else "in_progress"
    mastery = progress.mastery_score if progress else 0
    text = (
        f"{feedback}\n\n"
        f"<b>Сессия завершена</b>\n"
        f"Верно: {session.correct_answers_count}\n"
        f"Ошибок: {session.wrong_answers_count}\n"
        f"Тема: {_topic_title(topic_id)}\n"
        f"Статус: {status}\n"
        f"Освоение: {mastery}"
    )
    return GrammarResponseDTO(
        message_text=text,
        buttons=[
            [_button("Повторить тему", f"grammar:practice:{topic_id}") if topic_id else _button("Грамматика", "grammar:home")],
            [_button("Слабые темы", "grammar:weak")],
            [_button("Назад к грамматике", "grammar:home")],
        ],
        state_update={"module": "grammar", "state": "grammar_completed", "session_id": session.session_id},
        side_effects={"progress_updated": True, "session_created": False},
    )


def _start_session_response(session) -> GrammarResponseDTO:
    exercise = get_current_exercise(session.session_id)
    if not exercise:
        abandon_user_sessions(session.user_id)
        return GrammarResponseDTO(
            message_text="Подходящие упражнения пока недоступны. Попробуй другую тему.",
            buttons=[[_button("Назад к грамматике", "grammar:home")]],
        )
    return _render_exercise(
        session.session_id,
        exercise,
        session.current_exercise_index,
        len(session.exercise_queue_json),
    )


def _resolve_answer_from_payload(session_id: str, payload: dict) -> str:
    if "answer" in payload:
        return str(payload["answer"])
    if "option_index" in payload:
        exercise = get_current_exercise(session_id)
        if exercise and exercise.options:
            idx = int(payload["option_index"])
            if 0 <= idx < len(exercise.options):
                return exercise.options[idx]
    return ""


def _render_stale_answer_message() -> GrammarResponseDTO:
    return GrammarResponseDTO(
        message_text="Это ответ на старое задание. Используй только кнопки или сообщение из текущего упражнения.",
        buttons=[[_button("Открыть текущий экран", "grammar:home")]],
    )


def handle_grammar_event(event: GrammarEventDTO) -> GrammarResponseDTO:
    if not config.grammar_module_enabled():
        return GrammarResponseDTO(message_text="Раздел грамматики сейчас выключен.")

    try:
        if event.action == GrammarAction.OPEN_HOME:
            return _render_home(event.level, event.user_id)

        if event.action == GrammarAction.LIST_TOPICS:
            return _render_topic_list(event.user_id, event.level)

        if event.action == GrammarAction.OPEN_TOPIC:
            if not event.topic_id:
                return GrammarResponseDTO(message_text="Тема не найдена.", buttons=[[_button("Назад", "grammar:list_topics")]])
            return _render_theory(event.topic_id)

        if event.action == GrammarAction.START_TOPIC_PRACTICE:
            if not event.topic_id:
                return GrammarResponseDTO(message_text="Не выбрана тема для практики.")
            session = create_topic_session(event.user_id, event.chat_id, event.level, event.topic_id)
            return _start_session_response(session)

        if event.action == GrammarAction.START_WEAK_TOPICS_REVIEW:
            if not config.grammar_review_enabled():
                return GrammarResponseDTO(message_text="Повторы по грамматике сейчас выключены.")
            session = create_weak_topics_review_session(event.user_id, event.chat_id, event.level)
            return _start_session_response(session)

        if event.action == GrammarAction.START_MISTAKES_REVIEW:
            if not config.grammar_review_enabled():
                return GrammarResponseDTO(message_text="Повторы по грамматике сейчас выключены.")
            session = create_mistakes_review_session(event.user_id, event.chat_id, event.level)
            return _start_session_response(session)

        if event.action == GrammarAction.TOGGLE_NOTIFICATIONS:
            current = database.get_grammar_notifications_enabled(int(event.user_id))
            database.set_grammar_notifications_enabled(int(event.user_id), not current)
            response = _render_home(event.level, event.user_id)
            response.message_text = (
                "Напоминания по грамматике включены." if not current else "Напоминания по грамматике выключены."
            ) + "\n\n" + response.message_text
            return response

        if event.action == GrammarAction.EXIT_GRAMMAR:
            abandon_user_sessions(event.user_id)
            response = _render_home(event.level, event.user_id)
            response.message_text = "Сессия по грамматике завершена.\n\n" + response.message_text
            return response

        if event.action == GrammarAction.SUBMIT_ANSWER:
            session_id = event.session_id or event.payload.get("session_id")
            session = get_session(session_id) if session_id else get_active_session(event.user_id)
            if not session:
                return GrammarResponseDTO(
                    message_text="Сессия по грамматике не найдена. Начни заново.",
                    buttons=[[_button("Открыть грамматику", "grammar:home")]],
                )
            exercise = get_current_exercise(session.session_id)
            if not exercise:
                completed = complete_session(session.session_id)
                return _render_session_summary(completed, "Сессия уже завершена.")

            expected_exercise_index = event.payload.get("exercise_index")
            if expected_exercise_index is not None and int(expected_exercise_index) != session.current_exercise_index:
                return _render_stale_answer_message()

            if event.payload.get("skip"):
                session = advance_after_skip(session.session_id)
                feedback = "Задание пропущено. Переходим дальше."
                next_exercise = get_current_exercise(session.session_id)
                if not next_exercise:
                    completed = complete_session(session.session_id)
                    return _render_session_summary(completed, feedback)
                set_session_state(session.session_id, "awaiting_answer")
                next_response = _render_exercise(
                    session.session_id,
                    next_exercise,
                    session.current_exercise_index,
                    len(session.exercise_queue_json),
                )
                next_response.message_text = f"{feedback}\n\n{next_response.message_text}"
                return next_response

            user_answer = _resolve_answer_from_payload(session.session_id, event.payload)
            check_result = check_answer(exercise, user_answer)
            feedback = build_feedback(check_result, exercise)
            if not check_result.skipped:
                update_progress(session.user_id, exercise.topic_id, exercise, check_result)
                session = update_session_progress(session.session_id, check_result.is_correct)
            else:
                session = advance_after_skip(session.session_id)

            next_exercise = get_current_exercise(session.session_id)
            if not next_exercise:
                completed = complete_session(session.session_id)
                return _render_session_summary(completed, feedback)

            set_session_state(session.session_id, "awaiting_answer")
            next_response = _render_exercise(
                session.session_id,
                next_exercise,
                session.current_exercise_index,
                len(session.exercise_queue_json),
            )
            next_response.message_text = f"{feedback}\n\n{next_response.message_text}"
            next_response.side_effects = {"progress_updated": not check_result.skipped}
            return next_response

        return GrammarResponseDTO(message_text="Неизвестное действие Grammar.")
    except GrammarContentError:
        logger.exception("Grammar content error")
        return GrammarResponseDTO(
            message_text="Тема временно недоступна.",
            buttons=[[_button("Назад к грамматике", "grammar:home")]],
        )
    except Exception:
        logger.exception("Grammar module error")
        return GrammarResponseDTO(
            message_text="В разделе грамматики произошла ошибка. Попробуй снова.",
            buttons=[[_button("Назад к грамматике", "grammar:home")]],
        )
