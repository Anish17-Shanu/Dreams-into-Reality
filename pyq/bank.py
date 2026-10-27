"""Zero-cost PYQ ingestion, validation, and caching.

Data is fetched at runtime from public GitHub archives, validated locally,
and cached in the ``question`` table. No LLM, OCR, or paid API is used.
Only years whose answer keys were cross-checked are accepted for prelims.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timedelta

import requests
from flask import current_app
from sqlalchemy import func

from extensions import db
from models.models import PyqSyncState, Question
from pyq.taxonomy import classify_topic, is_self_contained

PRELIMS_SOURCE_URL = (
    "https://raw.githubusercontent.com/S-bandawala/upsc-quiz-app/main/data/beta_questions.json"
)
PRELIMS_FLAGGED_URL = (
    "https://raw.githubusercontent.com/S-bandawala/upsc-quiz-app/main/data/flagged_questions.json"
)
MAINS_SOURCE_URL = (
    "https://raw.githubusercontent.com/amanbh2/UPSC-Star/master/UPSC%20Star%20Data.json"
)

OFFICIAL_PYQ_URL = "https://www.upsc.gov.in/examinations/previous-question-papers"
OFFICIAL_ANSWER_KEY_URL = "https://www.upsc.gov.in/examinations/answer-key"

PYQ_ATTRIBUTION = (
    "Previous-year questions are compiled from public open-source archives "
    "(S-bandawala/upsc-quiz-app for prelims, amanbh2/UPSC-Star for mains). "
    "They are cached locally, not resold, and should always be cross-checked "
    "against the official UPSC papers and answer keys."
)

# 2016 and 2024-25 are excluded from scored tests because their answer keys
# were not verified against the official UPSC keys. They are still imported as
# "archive" practice so the questions are available with a clear warning.
VERIFIED_PRELIMS_YEARS = (2015, 2017, 2018, 2019, 2020, 2021, 2022, 2023)
ARCHIVE_PRELIMS_YEARS = (2016, 2024, 2025)
MAINS_PAPERS = {
    "GSI": ("GS-I", "History, Culture, Geography and Society"),
    "GSII": ("GS-II", "Polity, Governance and International Relations"),
    "GSIII": ("GS-III", "Economy, Environment, Science, Technology and Security"),
}

PRELIMS_SOURCE_NAME = "UPSC CSE Prelims GS-I"
MAINS_SOURCE_NAME = "UPSC CSE Mains"

_OPTION_PREFIX = re.compile(r"^\s*\(?([a-dA-D])\)?\s*[\.\):\-]\s*")
_EMBEDDED_OPTIONS = re.compile(r"\(\s*[a-dA-D]\s*\)")
_MULTISPACE = re.compile(r"\s+")
_DIRECTIVE = re.compile(
    r"\b(critically\s+)?(evaluate|examine|discuss|comment|analyse|analyze|"
    r"explain|elucidate|justify|assess|describe|illustrate|compare|contrast|"
    r"bring out|to what extent|how far)\b",
    re.IGNORECASE,
)

_SYNC_LOCK = threading.Lock()
_BACKGROUND_GUARD = threading.Lock()
_BACKGROUND_RUNNING = False
_MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


def _config(key, default=None):
    try:
        return current_app.config.get(key, default)
    except RuntimeError:
        return default


def _timeout():
    return _config("PYQ_REQUEST_TIMEOUT_SECONDS", 20)


def _refresh_days():
    return max(int(_config("PYQ_REFRESH_DAYS", 7) or 7), 1)


def _http_get_json(url, state=None):
    """Download JSON, sending conditional headers when a cached state exists.

    Returns ``(payload, not_modified)``. A 304 response keeps the existing
    cache and costs the archive host almost nothing.
    """
    headers = {
        "User-Agent": _config(
            "PYQ_USER_AGENT",
            "DreamsIntoReality/1.0 (free UPSC PYQ cache; contact: platform admin)",
        ),
        "Accept": "application/json",
    }
    if state is not None:
        if state.etag:
            headers["If-None-Match"] = state.etag
        if state.last_modified:
            headers["If-Modified-Since"] = state.last_modified
    response = requests.get(url, headers=headers, timeout=_timeout())
    if response.status_code == 304:
        return None, True
    response.raise_for_status()
    if len(response.content or b"") > _MAX_PAYLOAD_BYTES:
        raise ValueError("PYQ archive is unexpectedly large")
    payload = response.json()
    if state is not None:
        state.etag = (response.headers.get("ETag") or "")[:300] or None
        state.last_modified = (response.headers.get("Last-Modified") or "")[:120] or None
        state.content_hash = hashlib.sha256(response.content).hexdigest()
    return payload, False


def _clean_text(value):
    if not value:
        return ""
    return _MULTISPACE.sub(" ", str(value)).strip()


def _clean_option(value):
    text = _clean_text(value)
    return _OPTION_PREFIX.sub("", text).strip()


def _normalized_key(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _fetch_flagged_keys():
    try:
        payload, _ = _http_get_json(PRELIMS_FLAGGED_URL)
    except Exception as exc:  # pragma: no cover - network dependent
        _LOGGER.warning("Could not load flagged PYQ list: %s", exc)
        return set()
    keys = set()
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                keys.add((int(item.get("year")), int(item.get("q_num"))))
            except (TypeError, ValueError):
                continue
    return keys


def _validate_prelims_item(item, flagged, seen):
    try:
        year = int(item.get("year"))
        q_num = int(item.get("q_num"))
    except (TypeError, ValueError):
        return None, "bad_meta"
    if year not in VERIFIED_PRELIMS_YEARS and year not in ARCHIVE_PRELIMS_YEARS:
        return None, "unverified_year"
    if (year, q_num) in flagged:
        return None, "flagged"

    question = _clean_text(item.get("question"))
    if len(question) < 30 or len(question) > 1600:
        return None, "question_length"
    if not is_self_contained(question):
        return None, "figure_dependent"
    # A merged extraction contains a second set of (a)/(b)/(c)/(d) markers.
    if _EMBEDDED_OPTIONS.search(question):
        return None, "merged_options"

    options = [_clean_option(item.get(f"option_{letter}")) for letter in "abcd"]
    if any(not option or len(option) > 260 for option in options):
        return None, "bad_options"
    if len({option.casefold() for option in options}) < 4:
        return None, "duplicate_options"

    answer = str(item.get("correct_option", "")).strip().lower()
    if answer not in {"a", "b", "c", "d"}:
        return None, "bad_answer"

    key = _normalized_key(question)
    if key in seen:
        return None, "duplicate"
    seen.add(key)

    subject = _clean_text(item.get("topic")) or "General Studies"
    subtopic = _clean_text(item.get("subtopic"))
    subject, topic = classify_topic(question, subject, subtopic)
    difficulty = _clean_text(item.get("difficulty")).lower()
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"
    verified = year in VERIFIED_PRELIMS_YEARS

    return {
        "exam": "UPSC",
        "subject": subject[:120],
        "topic": topic[:160],
        "question_text": question,
        "answer_text": None,
        "difficulty": difficulty,
        "stage": "prelims",
        "year": year,
        "paper": "GS Paper I",
        "options_json": json.dumps(options, ensure_ascii=False),
        "correct_answer": answer,
        "source_url": OFFICIAL_PYQ_URL,
        "source_name": (
            f"{PRELIMS_SOURCE_NAME} {year} (open archive; official key verified)"
            if verified
            else f"{PRELIMS_SOURCE_NAME} {year} (open archive; key not officially verified)"
        ),
        "external_id": f"prelims:{year}:{q_num}",
        "quality_score": 1.0 if verified else 0.8,
        "verification": "verified" if verified else "archive",
        "is_public": True,
    }, ""


def _mains_directive(question):
    match = _DIRECTIVE.search(question)
    if not match:
        return "Explain"
    text = match.group(0).strip()
    return text[:1].upper() + text[1:].lower()


def _mains_framework(question, paper_label, marks, word_limit):
    directive = _mains_directive(question)
    limit = word_limit or (150 if marks <= 10 else 250)
    intro = 30 if limit <= 150 else 50
    return (
        "Answer framework (rule-based, not a model answer)\n"
        f"Directive: {directive}. Take a clear position in the introduction and keep it through the answer.\n"
        f"Structure for {paper_label} ({marks} marks, ~{limit} words):\n"
        f"1. Introduction (~{intro} words): define the core term, give the context, and state your stand.\n"
        "2. Body: 2-4 labelled dimensions with one concrete example or data point per dimension; "
        "where the question asks you to evaluate, add both an argument and a counter-argument.\n"
        "3. Conclusion: answer the exact directive, then add one forward-looking line on the way ahead.\n"
        "Presentation: short paragraphs, sub-headings where useful, and underline only key terms.\n"
        "Common traps: drifting into a general essay, listing facts without linking them to the directive, "
        "and ignoring the word limit.\n"
        "This is a preparation scaffold. Verify facts and figures from official sources before quoting them."
    )


def _validate_mains_item(item, paper_key, seen):
    if not isinstance(item, dict):
        return None, "bad_item"
    question = _clean_text(item.get("Question"))
    if len(question) < 25 or len(question) > 1200:
        return None, "question_length"
    if not is_self_contained(question):
        return None, "figure_dependent"
    try:
        year = int(item.get("Year"))
        marks = int(item.get("Marks") or 0)
        word_limit = int(item.get("WordLimit") or 0)
        source_id = int(item.get("Id"))
    except (TypeError, ValueError):
        return None, "bad_meta"
    if year < 2013 or year > 2025:
        return None, "bad_year"
    if not 5 <= marks <= 25:
        return None, "bad_marks"
    if not 50 <= word_limit <= 400:
        return None, "bad_word_limit"
    if paper_key not in MAINS_PAPERS:
        return None, "bad_paper"

    paper_label, paper_subject = MAINS_PAPERS[paper_key]
    key = _normalized_key(question)
    if key in seen:
        return None, "duplicate"
    seen.add(key)

    subject, topic = classify_topic(question, paper_subject, paper_label)
    return {
        "exam": "UPSC",
        "subject": subject[:120],
        "topic": topic[:160],
        "question_text": question,
        "answer_text": _mains_framework(question, paper_label, marks, word_limit),
        "difficulty": "hard" if marks >= 15 else "medium",
        "stage": "mains",
        "year": year,
        "paper": paper_label,
        "options_json": None,
        "correct_answer": None,
        "source_url": OFFICIAL_PYQ_URL,
        "source_name": f"{MAINS_SOURCE_NAME} {paper_label} {year} (open archive)",
        "external_id": f"mains:{paper_label}:{year}:{source_id}",
        "quality_score": 1.0,
        "verification": "archive",
        "is_public": True,
    }, ""


def _state_for(source):
    state = PyqSyncState.query.filter_by(source=source).first()
    if state is None:
        state = PyqSyncState(source=source)
        db.session.add(state)
    return state


def _set_state(source, status, count=None, detail=None):
    state = _state_for(source)
    state.status = status
    if count is not None:
        state.item_count = count
    if detail is not None:
        state.detail = detail[:300]
    if status == "done":
        state.last_synced_at = datetime.utcnow()
    db.session.commit()


def _upsert_questions(prefix, records):
    incoming = {record["external_id"]: record for record in records}
    existing = {
        row.external_id: row
        for row in Question.query.filter(Question.external_id.like(f"{prefix}:%")).all()
    }
    created = 0
    updated = 0
    for external_id, payload in incoming.items():
        row = existing.pop(external_id, None)
        if row is None:
            db.session.add(Question(**payload))
            created += 1
            continue
        changed = False
        for field, value in payload.items():
            if getattr(row, field) != value:
                setattr(row, field, value)
                changed = True
        if changed:
            updated += 1

    # Old rows that no longer pass validation stay in the database for history,
    # but are hidden from quizzes and coverage counts.
    retired = 0
    for row in existing.values():
        if row.is_public:
            row.is_public = False
            retired += 1
    db.session.commit()
    return created, updated, retired


def _sync_prelims():
    state = _state_for("prelims")
    previous_hash = state.content_hash
    _set_state("prelims", "running", detail="Downloading prelims archive")
    flagged = _fetch_flagged_keys()
    payload, not_modified = _http_get_json(PRELIMS_SOURCE_URL, state=state)
    if not_modified:
        _set_state(
            "prelims",
            "done",
            detail="Source unchanged (HTTP 304); cached questions kept.",
        )
        return state.item_count or 0
    if not isinstance(payload, list):
        raise ValueError("Unexpected prelims payload")

    seen = set()
    records = []
    rejected = {}
    for item in payload:
        record, reason = _validate_prelims_item(item, flagged, seen)
        if record is None:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        records.append(record)

    if len(records) < 200:
        raise ValueError(f"Only {len(records)} valid prelims questions; refusing to replace cache")

    created, updated, retired = _upsert_questions("prelims", records)
    unchanged = " (content unchanged)" if previous_hash and previous_hash == state.content_hash else ""
    detail = (
        f"{len(records)} valid prelims PYQs "
        f"({created} new, {updated} updated, {retired} retired){unchanged}"
    )
    _set_state("prelims", "done", count=len(records), detail=detail)
    _LOGGER.info("PYQ prelims sync: %s; rejected=%s", detail, rejected)
    return len(records)


def _sync_mains():
    state = _state_for("mains")
    previous_hash = state.content_hash
    _set_state("mains", "running", detail="Downloading mains archive")
    payload, not_modified = _http_get_json(MAINS_SOURCE_URL, state=state)
    if not_modified:
        _set_state(
            "mains",
            "done",
            detail="Source unchanged (HTTP 304); cached questions kept.",
        )
        return state.item_count or 0
    if not isinstance(payload, dict):
        raise ValueError("Unexpected mains payload")

    seen = set()
    records = []
    for paper_key in ("GSI", "GSII", "GSIII"):
        items = payload.get(paper_key)
        if not isinstance(items, list):
            continue
        for item in items:
            record, _reason = _validate_mains_item(item, paper_key, seen)
            if record is not None:
                records.append(record)

    if len(records) < 100:
        raise ValueError(f"Only {len(records)} valid mains questions; refusing to replace cache")

    created, updated, retired = _upsert_questions("mains", records)
    unchanged = " (content unchanged)" if previous_hash and previous_hash == state.content_hash else ""
    detail = (
        f"{len(records)} valid mains PYQs "
        f"({created} new, {updated} updated, {retired} retired){unchanged}"
    )
    _set_state("mains", "done", count=len(records), detail=detail)
    _LOGGER.info("PYQ mains sync: %s", detail)
    return len(records)


def _fresh(state):
    if state is None or state.status != "done" or not state.last_synced_at:
        return False
    if not state.item_count:
        return False
    return datetime.utcnow() - state.last_synced_at < timedelta(days=_refresh_days())


def coverage_stats():
    """Return a defensive snapshot used by templates and the quiz flow."""
    stats = {
        "prelims_total": 0,
        "mains_total": 0,
        "by_year": {},
        "years": [],
        "prelims_state": None,
        "mains_state": None,
        "last_synced_at": None,
        "refresh_days": _refresh_days(),
        "attribution": PYQ_ATTRIBUTION,
        "official_url": OFFICIAL_PYQ_URL,
        "answer_key_url": OFFICIAL_ANSWER_KEY_URL,
        "verification": {},
        "verified_total": 0,
        "archive_total": 0,
        "mains_by_year": {},
        "top_topics": [],
        "seed_available": False,
    }
    try:
        from pyq.seed import seed_available

        stats["seed_available"] = seed_available()
    except Exception:  # pragma: no cover - optional module
        stats["seed_available"] = False
    try:
        stats["prelims_total"] = (
            Question.query.filter_by(stage="prelims", is_public=True).count()
        )
        stats["mains_total"] = (
            Question.query.filter_by(stage="mains", is_public=True).count()
        )
        rows = (
            db.session.query(Question.year, func.count(Question.id))
            .filter(Question.stage == "prelims", Question.is_public.is_(True))
            .group_by(Question.year)
            .all()
        )
        by_year = {int(year): int(count) for year, count in rows if year}
        stats["by_year"] = dict(sorted(by_year.items()))
        stats["years"] = sorted(by_year)

        mains_rows = (
            db.session.query(Question.year, func.count(Question.id))
            .filter(Question.stage == "mains", Question.is_public.is_(True))
            .group_by(Question.year)
            .all()
        )
        stats["mains_by_year"] = dict(
            sorted({int(year): int(count) for year, count in mains_rows if year}.items())
        )

        verification_rows = (
            db.session.query(Question.stage, Question.verification, func.count(Question.id))
            .filter(Question.is_public.is_(True))
            .group_by(Question.stage, Question.verification)
            .all()
        )
        verification = {}
        for stage, status, count in verification_rows:
            stage = stage or "other"
            status = status or "archive"
            verification.setdefault(stage, {})[status] = int(count)
            if status == "verified":
                stats["verified_total"] += int(count)
            else:
                stats["archive_total"] += int(count)
        stats["verification"] = verification

        topic_rows = (
            db.session.query(Question.topic, func.count(Question.id))
            .filter(
                Question.stage == "prelims",
                Question.is_public.is_(True),
                Question.topic.isnot(None),
            )
            .group_by(Question.topic)
            .order_by(func.count(Question.id).desc())
            .limit(12)
            .all()
        )
        stats["top_topics"] = [
            {"topic": topic, "count": int(count)} for topic, count in topic_rows if topic
        ]

        prelims_state = PyqSyncState.query.filter_by(source="prelims").first()
        mains_state = PyqSyncState.query.filter_by(source="mains").first()
        for key, state in (("prelims_state", prelims_state), ("mains_state", mains_state)):
            if state is not None:
                stats[key] = {
                    "status": state.status,
                    "item_count": state.item_count,
                    "detail": state.detail,
                    "last_synced_at": state.last_synced_at,
                }
        stamps = [
            state.last_synced_at
            for state in (prelims_state, mains_state)
            if state is not None and state.last_synced_at
        ]
        stats["last_synced_at"] = max(stamps) if stamps else None
    except Exception:  # pragma: no cover - unmigrated schemas
        _LOGGER.exception("Could not compute PYQ coverage")
    return stats


def sync_pyq(force=False, wait=False):
    """Fetch and cache PYQs. Individual sources fail independently."""
    if not _config("PYQ_SYNC_ENABLED", True):
        return coverage_stats()
    try:
        prelims_state = PyqSyncState.query.filter_by(source="prelims").first()
        mains_state = PyqSyncState.query.filter_by(source="mains").first()
        if not force and _fresh(prelims_state) and _fresh(mains_state):
            return coverage_stats()
    except Exception:  # pragma: no cover - unmigrated schemas
        _LOGGER.exception("Could not read PYQ sync state")

    if wait:
        acquired = _SYNC_LOCK.acquire(timeout=_timeout() * 3)
    else:
        acquired = _SYNC_LOCK.acquire(blocking=False)
    if not acquired:
        return coverage_stats()

    try:
        # Another worker may have completed the sync while we waited.
        prelims_state = PyqSyncState.query.filter_by(source="prelims").first()
        mains_state = PyqSyncState.query.filter_by(source="mains").first()
        if not force and _fresh(prelims_state) and _fresh(mains_state):
            return coverage_stats()
        if force or not _fresh(prelims_state):
            try:
                _sync_prelims()
            except Exception as exc:
                db.session.rollback()
                _LOGGER.exception("Prelims PYQ sync failed")
                _set_state("prelims", "failed", detail=f"Prelims sync failed: {exc}")
        if force or not _fresh(mains_state):
            try:
                _sync_mains()
            except Exception as exc:
                db.session.rollback()
                _LOGGER.exception("Mains PYQ sync failed")
                _set_state("mains", "failed", detail=f"Mains sync failed: {exc}")
    finally:
        _SYNC_LOCK.release()
    return coverage_stats()


def _spawn_background_sync(app):
    global _BACKGROUND_RUNNING
    with _BACKGROUND_GUARD:
        if _BACKGROUND_RUNNING:
            return
        _BACKGROUND_RUNNING = True

    def runner():
        global _BACKGROUND_RUNNING
        try:
            with app.app_context():
                sync_pyq(force=False)
        except Exception:  # pragma: no cover - background safety
            _LOGGER.exception("Background PYQ sync failed")
        finally:
            with _BACKGROUND_GUARD:
                _BACKGROUND_RUNNING = False

    threading.Thread(target=runner, name="pyq-sync", daemon=True).start()


def ensure_pyq_synced(force=False, wait=False):
    """Never raise into a request; return the best available cache state.

    The bundled seed keeps first-run tests usable. When a cached bank exists
    but is due for refresh, the download happens in the background so a page
    request is never held hostage by a slow archive host.
    """
    try:
        try:
            from pyq.seed import seed_bank

            seed_bank()
        except Exception:  # pragma: no cover - seed is optional
            _LOGGER.exception("Could not load the PYQ seed")
        stats = coverage_stats()
        prelims_ready = stats["prelims_total"] >= 50
        mains_ready = stats["mains_total"] >= 50
        if not force and prelims_ready and mains_ready:
            prelims_state = PyqSyncState.query.filter_by(source="prelims").first()
            mains_state = PyqSyncState.query.filter_by(source="mains").first()
            if _fresh(prelims_state) and _fresh(mains_state):
                return stats
            if not wait:
                _spawn_background_sync(current_app._get_current_object())
                return stats
        # The very first test should wait for the download instead of
        # redirecting the user simply because a background sync is running.
        return sync_pyq(force=force, wait=wait or not prelims_ready)
    except Exception:  # pragma: no cover - defensive
        _LOGGER.exception("PYQ sync wrapper failed")
        return coverage_stats()
