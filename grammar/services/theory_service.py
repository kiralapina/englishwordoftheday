"""Theory service."""

from grammar.content_loader import get_topic_theory
from grammar.dto import TheoryDTO


def load_topic_theory(topic_id: str) -> TheoryDTO:
    return get_topic_theory(topic_id)
