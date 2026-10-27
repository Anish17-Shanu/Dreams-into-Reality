"""Free, zero-LLM previous-year-question support for Dreams into Reality."""

from pyq.bank import (
    OFFICIAL_ANSWER_KEY_URL,
    OFFICIAL_PYQ_URL,
    PYQ_ATTRIBUTION,
    coverage_stats,
    ensure_pyq_synced,
    sync_pyq,
)
from pyq.service import (
    get_interview_set,
    mains_questions,
    prelims_questions,
    subject_keywords_for_topics,
)

__all__ = [
    "OFFICIAL_ANSWER_KEY_URL",
    "OFFICIAL_PYQ_URL",
    "PYQ_ATTRIBUTION",
    "coverage_stats",
    "ensure_pyq_synced",
    "sync_pyq",
    "get_interview_set",
    "mains_questions",
    "prelims_questions",
    "subject_keywords_for_topics",
]
