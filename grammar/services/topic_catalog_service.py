"""Topic catalog service."""

from grammar.content_loader import get_topics_for_level
from grammar.dto import GrammarTopicDTO
from grammar.enums import TopicStatus
from grammar.repositories import list_topic_progress


def get_topics_for_user_level(level: str, user_id: str) -> list[GrammarTopicDTO]:
    topics = get_topics_for_level(level)
    progress_map = list_topic_progress(user_id)
    result: list[GrammarTopicDTO] = []
    for topic in topics:
        progress = progress_map.get(topic.topic_id)
        if progress:
            result.append(
                topic.model_copy(
                    update={
                        "status": TopicStatus(progress.status),
                        "mastery_score": progress.mastery_score,
                    }
                )
            )
        else:
            result.append(topic)
    return result
