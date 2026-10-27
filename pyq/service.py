"""Selection helpers for cached PYQs. Pure database reads, no network or LLM."""

from __future__ import annotations

import json
import random

from models.models import Question
from pyq.taxonomy import canonical_subject, is_self_contained, normalize_text, selector_keywords

PRELIMS_SUBJECTS = (
    "Polity",
    "History",
    "Geography",
    "Economy",
    "Environment",
    "Science & Technology",
    "International Relations",
    "Current Affairs",
)

_SUBJECT_ALIASES = {
    "polity": "Polity",
    "constitution": "Polity",
    "governance": "Polity",
    "parliament": "Polity",
    "judiciary": "Polity",
    "federalism": "Polity",
    "history": "History",
    "culture": "History",
    "heritage": "History",
    "geography": "Geography",
    "economy": "Economy",
    "economics": "Economy",
    "environment": "Environment",
    "ecology": "Environment",
    "science & technology": "Science & Technology",
    "science and technology": "Science & Technology",
    "science": "Science & Technology",
    "technology": "Science & Technology",
    "international relations": "International Relations",
    "international relation": "International Relations",
    "ir": "International Relations",
    "current affairs": "Current Affairs",
    "current affair": "Current Affairs",
}

_TOPIC_SUBJECT_HINTS = (
    ("International Relations", (
        "international relation", "foreign policy", "diplomacy", "geopolitics",
        "united nations", "global governance", "bilateral",
    )),
    ("Science & Technology", (
        "science", "technology", "biotech", "space", "nuclear", "artificial intelligence",
        "defence technology", "health technology", "digital",
    )),
    ("Environment", (
        "environment", "ecology", "biodiversity", "climate change", "conservation",
        "pollution", "wildlife",
    )),
    ("Economy", (
        "economy", "economics", "budget", "fiscal", "monetary", "banking", "tax",
        "agriculture", "trade", "industry", "inflation", "gdp", "finance",
    )),
    ("Geography", (
        "geography", "climate", "monsoon", "physical geography", "human geography",
        "ocean", "soil", "map",
    )),
    ("History", (
        "history", "culture", "heritage", "freedom struggle", "ancient", "medieval",
        "modern india", "world history", "art and culture",
    )),
    ("Polity", (
        "polity", "constitution", "parliament", "judiciary", "federalism",
        "governance", "social justice", "panchayat", "election", "president",
        "governor", "constitutional",
    )),
    ("Current Affairs", (
        "current affairs", "government scheme", "scheme", "report", "index",
        "internal security", "disaster management", "society", "social issue",
    )),
)


def _canonical_subject(value):
    text = (value or "").strip().lower()
    if not text:
        return None
    for canonical in PRELIMS_SUBJECTS:
        if text == canonical.lower():
            return canonical
    for alias, canonical in _SUBJECT_ALIASES.items():
        if alias in text:
            return canonical
    return None


def subject_keywords_for_topics(topics):
    """Map free-form roadmap topics to the eight prelims subject buckets."""
    found = []
    for topic in topics or []:
        text = str(topic or "").strip().lower()
        if not text:
            continue
        for canonical, hints in _TOPIC_SUBJECT_HINTS:
            if canonical in found:
                continue
            if any(hint in text for hint in hints):
                found.append(canonical)
    return found


def _normalize_text(text):
    return " ".join(str(text or "").lower().split())


def _decode_options(row):
    try:
        options = json.loads(row.options_json or "[]")
    except (TypeError, ValueError):
        return None
    if not isinstance(options, list) or len(options) != 4:
        return None
    cleaned = [str(option).strip() for option in options]
    if any(not option for option in cleaned):
        return None
    if len({option.casefold() for option in cleaned}) < 4:
        return None
    return cleaned


def _prelims_payload(row, subject=None):
    options = _decode_options(row)
    answer = (row.correct_answer or "").strip().lower()
    if options is None or answer not in {"a", "b", "c", "d"}:
        return None
    return {
        "id": row.id,
        "stage": "prelims",
        "question": row.question_text,
        "options": options,
        "correct": answer,
        "subject": subject or row.subject or "General Studies",
        "topic": row.topic or "",
        "year": row.year,
        "paper": row.paper or "GS Paper I",
        "difficulty": row.difficulty or "medium",
        "source": row.source_name or "UPSC previous-year paper",
        "source_url": row.source_url,
        "verification": row.verification or "archive",
        "review_note": (
            "The official UPSC answer key is the final authority. "
            "Re-read the question stem and eliminate options with absolute language."
        ),
    }


def _topic_terms(topics):
    """Split weak areas into exact-topic terms and broader subject terms.

    A retest for "Judiciary" should not fill the paper with arbitrary Polity
    questions just because the subject label matches.
    """
    topic_terms = set()
    subject_terms = set()
    for topic in topics or []:
        normalized = normalize_text(topic)
        if not normalized:
            continue
        subject = canonical_subject(topic)
        subject_key = normalize_text(subject) if subject else None
        for keyword in selector_keywords(topic):
            term = normalize_text(keyword)
            if len(term) < 3:
                continue
            if subject_key and term == subject_key:
                subject_terms.add(term)
            else:
                topic_terms.add(term)
        if not subject and normalized:
            topic_terms.update(word for word in normalized.split() if len(word) >= 3)
    return {"topics": topic_terms, "subjects": subject_terms}


def _match_rank(payload, terms):
    if not terms["topics"] and not terms["subjects"]:
        return 0
    haystack = normalize_text(
        f"{payload.get('topic', '')} {payload.get('subject', '')} {payload.get('question', '')}"
    )
    if any(term in haystack for term in terms["topics"]):
        return 0
    if any(term in haystack for term in terms["subjects"]):
        return 1
    return 2


def _prelims_candidates(years=None, exclude_texts=None, rng=None, topics=None,
                        exclude_ids=None, include_unverified=False,
                        archive_only=False):
    rows = (
        Question.query.filter_by(stage="prelims", is_public=True)
        .filter(Question.options_json.isnot(None), Question.correct_answer.isnot(None))
        .all()
    )
    allowed_years = {int(year) for year in years} if years else None
    excluded = {_normalize_text(text) for text in (exclude_texts or []) if text}
    excluded_ids = {int(item) for item in (exclude_ids or []) if str(item).isdigit()}
    terms = _topic_terms(topics)
    candidates = []
    for row in rows:
        if row.id in excluded_ids:
            continue
        if allowed_years is not None and row.year not in allowed_years:
            continue
        if excluded and _normalize_text(row.question_text) in excluded:
            continue
        if not is_self_contained(row.question_text):
            continue
        payload = _prelims_payload(row)
        if payload is None:
            continue
        verified = payload.get("verification") in {"verified", "imported"}
        if archive_only and verified:
            continue
        if not include_unverified and not archive_only and not verified:
            continue
        candidates.append(payload)
    if rng is not None:
        rng.shuffle(candidates)
    else:
        random.shuffle(candidates)
    if terms or candidates:
        # Verified questions first, then exact-topic matches, then broader
        # subject matches, while keeping randomness inside each bucket.
        candidates.sort(
            key=lambda item: (
                0 if item.get("verification") in {"verified", "imported"} else 1,
                _match_rank(item, terms),
            )
        )
    return candidates


def _spread_by_year(items, amount, rng=None):
    buckets = {}
    for item in items:
        buckets.setdefault(item.get("year"), []).append(item)
    ordered = []
    years = list(buckets)
    if rng is not None:
        rng.shuffle(years)
    else:
        random.shuffle(years)
    while len(ordered) < amount and any(buckets.values()):
        for year in years:
            if buckets[year]:
                ordered.append(buckets[year].pop())
                if len(ordered) >= amount:
                    break
    return ordered


def prelims_questions(amount=10, subjects=None, years=None, exclude_texts=None, rng=None,
                      spread_years=False, topics=None, exclude_ids=None,
                      include_unverified=False, archive_only=False):
    """Return validated prelims PYQs, preferring the roadmap's subjects/topics.

    Subject and topic matching is a preference, never a hard requirement: when a
    roadmap covers Ethics or CSAT there may be no mapped prelims bucket, so the
    test is filled with the remaining verified PYQs instead of dropping to trivia.
    """
    try:
        amount = max(int(amount), 1)
    except (TypeError, ValueError):
        amount = 10

    candidates = _prelims_candidates(
        years=years,
        exclude_texts=exclude_texts,
        rng=rng,
        topics=topics,
        exclude_ids=exclude_ids,
        include_unverified=include_unverified,
        archive_only=archive_only,
    )
    if not candidates:
        return []

    wanted = {
        canonical
        for canonical in (_canonical_subject(subject) for subject in (subjects or []))
        if canonical
    }
    if not wanted:
        if spread_years:
            return _spread_by_year(candidates, amount, rng)
        return candidates[:amount]

    matched = []
    others = []
    for payload in candidates:
        canonical = _canonical_subject(payload["subject"])
        if canonical in wanted:
            matched.append(payload)
        else:
            others.append(payload)

    if len(matched) >= amount:
        return matched[:amount]

    # Keep at least 70% of the paper tied to the roadmap when possible.
    target_matched = min(len(matched), max(amount - len(others), int(round(amount * 0.7))))
    selected = matched[:target_matched]
    remaining = amount - len(selected)
    if remaining > 0:
        selected.extend(others[:remaining])
    if len(selected) < amount:
        leftover = [item for item in matched[target_matched:] if item not in selected]
        selected.extend(leftover[: amount - len(selected)])
    selected = selected[:amount]
    if spread_years:
        return _spread_by_year(selected, amount, rng)
    return selected


def _mains_candidates(papers=None, exclude_texts=None, rng=None):
    rows = Question.query.filter_by(stage="mains", is_public=True).all()
    allowed_papers = {str(paper).strip() for paper in papers or [] if str(paper).strip()}
    excluded = {_normalize_text(text) for text in (exclude_texts or []) if text}
    candidates = []
    for row in rows:
        if allowed_papers and (row.paper or "") not in allowed_papers:
            continue
        if excluded and _normalize_text(row.question_text) in excluded:
            continue
        if not is_self_contained(row.question_text):
            continue
        candidates.append({
            "id": row.id,
            "stage": "mains",
            "question": row.question_text,
            "paper": row.paper or "",
            "year": row.year,
            "subject": row.subject or "",
            "topic": row.topic or "",
            "difficulty": row.difficulty or "hard",
            "source": row.source_name or "UPSC previous-year paper",
            "source_url": row.source_url,
            "verification": row.verification or "archive",
            "framework": row.answer_text or "",
        })
    if rng is not None:
        rng.shuffle(candidates)
    else:
        random.shuffle(candidates)
    return candidates


def mains_questions(amount=5, papers=None, exclude_texts=None, rng=None):
    try:
        amount = max(int(amount), 1)
    except (TypeError, ValueError):
        amount = 5
    return _mains_candidates(papers=papers, exclude_texts=exclude_texts, rng=rng)[:amount]


_INTERVIEW_PROMPTS = (
    {
        "prompt": "Walk us through your background and explain why public administration is the right next step for you.",
        "dimension": "DAF and motivation",
        "approach": "Use a 60-90 second arc: background, turning point, what you have tested, and why this service. Avoid a resume recital.",
        "follow_up": "Which part of that story would you change if you had one more year to prepare?",
    },
    {
        "prompt": "You are posted in a district where a new welfare scheme is being resisted by local intermediaries. How would you proceed?",
        "dimension": "Administrative judgement",
        "approach": "Diagnose the resistance, map stakeholders, protect beneficiaries, use existing institutions, and keep a feedback loop. Give a sequence, not a slogan.",
        "follow_up": "What would make you pause and redesign the rollout?",
    },
    {
        "prompt": "Is a neutral civil servant possible in a politically charged environment? Give your view with examples.",
        "dimension": "Ethics and constitutional values",
        "approach": "Separate political neutrality from policy neutrality. Anchor on the Constitution, due process, and documented decision-making.",
        "follow_up": "Where is the line between responsiveness and compliance?",
    },
    {
        "prompt": "Your optional subject is {optional}. How does it shape the way you analyse governance problems?",
        "dimension": "Optional subject and thinking style",
        "approach": "Name two concepts from the subject, apply each to a live governance problem, and admit one limitation.",
        "follow_up": "Give an example where your subject's framework would mislead you.",
    },
    {
        "prompt": "India wants faster growth and lower emissions at the same time. What would you prioritise in the next five years?",
        "dimension": "Current affairs and trade-offs",
        "approach": "State the trade-off clearly, choose a sequencing, and support it with two concrete levers such as energy efficiency and public transport.",
        "follow_up": "Who bears the short-term cost of your choice?",
    },
    {
        "prompt": "Social media has changed how citizens see the state. Is this mostly healthy or mostly dangerous?",
        "dimension": "Balanced opinion",
        "approach": "Take a position, acknowledge the strongest counter-point, and propose one institutional safeguard.",
        "follow_up": "Would your answer change during a disaster or an election?",
    },
    {
        "prompt": "You disagree with a senior officer's decision that is legal but unfair to a vulnerable group. What do you do?",
        "dimension": "Ethics under hierarchy",
        "approach": "Use the chain of command, put the concern in writing, propose an alternative, and protect the affected people in the meantime.",
        "follow_up": "What if the senior officer asks you to sign the file immediately?",
    },
    {
        "prompt": "What is one failure that changed how you work, and what did you change afterwards?",
        "dimension": "Self-awareness",
        "approach": "Choose a real, modest failure. Spend most of the answer on the correction and the evidence that it stuck.",
        "follow_up": "What habit still tests you today?",
    },
    {
        "prompt": "Should welfare schemes be universal or targeted? Argue with Indian administrative experience.",
        "dimension": "Policy reasoning",
        "approach": "Compare inclusion errors and exclusion errors, then recommend a hybrid with a clear eligibility rule and a grievance channel.",
        "follow_up": "How would you measure whether the targeting worked?",
    },
    {
        "prompt": "A local newspaper accuses your office of corruption. You believe the allegation is false. How do you respond?",
        "dimension": "Crisis communication",
        "approach": "Verify facts, respond publicly with records, invite an audit, and avoid both defensiveness and trial by media.",
        "follow_up": "What if the audit finds a procedural lapse by your team?",
    },
    {
        "prompt": "Which one reform would you make to India's civil services, and what would it cost?",
        "dimension": "Institutional reform",
        "approach": "Pick one reform, name the implementation path, estimate the fiscal or political cost, and state how you would evaluate it.",
        "follow_up": "Why has this reform not happened already?",
    },
    {
        "prompt": "You have to convince a community to accept a project that is good for the region but displaces some families. How do you build consent?",
        "dimension": "Empathy and negotiation",
        "approach": "Start with listening, publish the evidence, offer fair compensation and resettlement, and keep a named grievance owner.",
        "follow_up": "What would you do if a small group still refuses?",
    },
)


def get_interview_set(profile=None, amount=8, rng=None):
    """Curated, original interview practice prompts with answer approaches."""
    profile = profile or {}
    optional = (profile.get("optional_subject") or "").strip()
    prompts = []
    for item in _INTERVIEW_PROMPTS:
        prompt = item["prompt"].replace("{optional}", optional or "your optional subject")
        prompts.append({**item, "prompt": prompt})
    picker = rng or random
    picker.shuffle(prompts)
    try:
        amount = max(int(amount), 1)
    except (TypeError, ValueError):
        amount = 8
    return prompts[:amount]
