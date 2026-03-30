"""Feedback message builder."""

from __future__ import annotations

from jinja2 import Template

from grammar.dto import CheckResultDTO, ExerciseDTO
from grammar.llm.explanation_generator import generate_short_explanation


CORRECT_TEMPLATE = Template("Верно. {{ explanation }}")
WRONG_TEMPLATE = Template(
    "Неверно. Правильный ответ: {{ correct_answer }}. {{ explanation }} Пример: {{ example }}"
)
SKIPPED_TEMPLATE = Template("Это задание пропущено: {{ reason }}")

RUSSIAN_EXPLANATIONS = {
    "to_be_form": "С глаголом to be нужно выбрать правильную форму: am, is или are.",
    "article_use": "Смотри на существительное и контекст: a/an для одного предмета, the для конкретного.",
    "subject_verb_agreement": "В Present Simple с he, she, it глагол обычно получает окончание -s или -es.",
    "there_is_are": "There is используется с одним предметом, there are с несколькими.",
    "past_simple_form": "В Past Simple для отрицаний и вопросов используется did, а основной глагол остаётся в начальной форме.",
    "present_continuous_form": "В Present Continuous нужна связка am/is/are + глагол с окончанием -ing.",
    "comparison_form": "Сравнения требуют правильной формы: -er / the -est или more / the most.",
    "future_form_choice": "Will чаще используется для спонтанного решения, going to — для плана или очевидного прогноза.",
    "present_perfect_form": "В Present Perfect нужна форма have/has + третья форма глагола.",
    "conditional_form": "В первом условном предложении после if идёт Present Simple, а в главной части — will.",
    "verb_pattern": "После некоторых глаголов нужен infinitive, а после других — форма на -ing.",
    "passive_form": "В пассиве нужна форма be + третья форма глагола.",
    "second_conditional_form": "Во втором условном используется If + Past Simple, а затем would + глагол.",
    "third_conditional_form": "В третьем условном используется If + Past Perfect, а затем would have + V3.",
    "wish_form": "После wish для сожаления используются формы прошедшего времени или past perfect.",
    "inversion_pattern": "После never, rarely, only then и похожих выражений в инверсии меняется порядок слов.",
    "mixed_conditional": "Смешанное условное связывает прошлую причину и результат в настоящем или наоборот.",
}


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_feedback(check_result: CheckResultDTO, exercise: ExerciseDTO) -> str:
    explanation = ""

    # LLM reason from transformation checker has the best context
    if check_result.reason and check_result.check_mode == "llm":
        explanation = check_result.reason.strip()

    if not explanation:
        explanation = RUSSIAN_EXPLANATIONS.get(exercise.mistake_type, "").strip()
    if not explanation:
        explanation = (exercise.explanation_template or "").strip()
    if not check_result.is_correct and not explanation:
        explanation = "Проверь правило этой темы и попробуй похожее задание ещё раз."

    if not check_result.is_correct and check_result.check_mode != "llm":
        llm_hint = generate_short_explanation(
            f"Exercise: {exercise.prompt}\nUser answer: {check_result.user_answer}\n"
            f"Correct answers: {exercise.correct_answers}\n"
            f"Explain in Russian in simple words for an English learner.\n"
            f"Rule: {exercise.explanation_template or ''}"
        )
        if llm_hint:
            explanation = llm_hint

    if check_result.skipped:
        return _clip(SKIPPED_TEMPLATE.render(reason=check_result.reason), 350)

    if check_result.is_correct:
        message = CORRECT_TEMPLATE.render(
            explanation=explanation or "Хорошая работа.",
        )
        return _clip(message, 350 if exercise.type != "sentence_transformation" else 500)

    extra_example = exercise.accepted_answers[0] if exercise.accepted_answers else "-"
    message = WRONG_TEMPLATE.render(
        correct_answer=exercise.correct_answers[0] if exercise.correct_answers else "-",
        explanation=explanation,
        example=extra_example,
    )
    return _clip(message, 350 if exercise.type != "sentence_transformation" else 500)
