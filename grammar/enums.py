"""Grammar module enums and constants."""

from enum import StrEnum


class GrammarAction(StrEnum):
    OPEN_HOME = "open_home"
    LIST_TOPICS = "list_topics"
    OPEN_TOPIC = "open_topic"
    START_TOPIC_PRACTICE = "start_topic_practice"
    SUBMIT_ANSWER = "submit_answer"
    START_WEAK_TOPICS_REVIEW = "start_weak_topics_review"
    START_MISTAKES_REVIEW = "start_mistakes_review"
    TOGGLE_NOTIFICATIONS = "toggle_notifications"
    EXIT_GRAMMAR = "exit_grammar"


class GrammarState(StrEnum):
    GRAMMAR_HOME = "grammar_home"
    TOPIC_LIST = "topic_list"
    TOPIC_THEORY = "topic_theory"
    TOPIC_PRACTICE = "topic_practice"
    AWAITING_ANSWER = "awaiting_answer"
    SHOWING_FEEDBACK = "showing_feedback"
    REVIEW_SESSION = "review_session"
    GRAMMAR_COMPLETED = "grammar_completed"


class ExerciseType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_IN_THE_GAP = "fill_in_the_gap"
    SENTENCE_TRANSFORMATION = "sentence_transformation"


class SessionMode(StrEnum):
    TOPIC_PRACTICE = "topic_practice"
    WEAK_TOPICS_REVIEW = "weak_topics_review"
    MISTAKES_REVIEW = "mistakes_review"


class TopicStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    MASTERED = "mastered"
