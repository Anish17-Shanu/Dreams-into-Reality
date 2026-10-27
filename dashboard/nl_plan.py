"""Deterministic natural-language plan understanding.

The platform is deliberately zero-cost, so this module uses a small set of
regexes instead of a model. It turns sentences such as "I want to become a
data analyst in 3 months, 2 hours a day" into the values the roadmap form
already understands.
"""
from __future__ import annotations

import re

_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_NUMBER_WORDS = "|".join(_WORD_NUMBERS)
_NUMBER = rf"(?:\d{{1,3}}(?:\.\d+)?|{_NUMBER_WORDS})"

_ROLE_NOUN_RE = re.compile(
    r"\b(?:engineer|developer|programmer|analyst|scientist|designer|manager|"
    r"consultant|architect|accountant|nurse|teacher|professor|lawyer|doctor|"
    r"pharmacist|writer|editor|marketer|specialist|technician|officer|executive|"
    r"administrator|therapist|biologist|chemist|physicist|economist|statistician|"
    r"journalist|photographer|chef|pilot|entrepreneur|recruiter|auditor|banker|"
    r"advisor|coach|trainer|librarian|translator|paralegal|dietitian|"
    r"veterinarian|surveyor|planner|curator|producer|director|strategist|"
    r"researcher|designer|artist|animator|illustrator|editor|copywriter|"
    r"electrician|mechanic|plumber|carpenter|judge|diplomat|principal|"
    r"businessman|businesswoman|businessperson|owner|freelancer|youtuber|"
    r"influencer|actor|actress|singer|dancer|athlete|soldier|receptionist|"
    r"secretary|clerk|cashier|waiter|waitress|hostess|servant|chef|baker|"
    r"tailor|driver|farmer|fisherman|guard|security|firefighter|paramedic)\b",
    re.IGNORECASE,
)
_NON_ROLE_ENDINGS = {
    "student", "learner", "beginner", "person", "people", "graduate",
    "topper", "achiever", "expert", "professional", "job-ready", "ready",
    "successful", "confident", "better", "good", "great",
}
_ROLE_STOP = (
    r"(?=\s+(?:in|within|by|over|for|with|at|and|who|which|that|starting|"
    r"from|to|before|after)\b|[,.;!?]|$)"
)
_ROLE_CHARS = r"[a-z][a-z0-9 &/+.'-]{2,60}?"

_ROLE_PATTERNS = (
    re.compile(
        rf"\b(?:want|plan|planning|hope|hoping|aim|aiming|dream|dreaming|try|trying|need|needing)"
        rf"\s+to\s+(?:become|be)\s+(?:a|an)?\s*({_ROLE_CHARS}){_ROLE_STOP}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:become|becoming)\s+(?:a|an)?\s*({_ROLE_CHARS}){_ROLE_STOP}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:work|working)\s+as\s+(?:a|an)?\s*({_ROLE_CHARS}){_ROLE_STOP}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:career|job|role|profession|position)\s+(?:as|in|of)\s+(?:a|an)?\s*"
        rf"({_ROLE_CHARS}){_ROLE_STOP}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:prepare|preparing|prep)\s+(?:me\s+)?(?:for|to\s+become)\s+"
        rf"(?:a|an)?\s*({_ROLE_CHARS}){_ROLE_STOP}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b({_ROLE_CHARS})\s+(?:career|career path|job|role|roadmap|plan)\b",
        re.IGNORECASE,
    ),
)

_SYLLABUS_TITLE_PATTERNS = (
    re.compile(
        r"\b(?:prepare|preparing|prep)\s+(?:me\s+)?for\s+(?:my\s+|the\s+)?([^,.;!?]{3,90})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|the)\s+([^,.;!?]{2,70}?)\s+"
        r"(exam|exams|test|tests|paper|papers|syllabus|prelims|mains|boards?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:study|studying|revise|revising|cover|covering|learn|learning|master|mastering)"
        r"\s+([^,.;!?]{3,90})",
        re.IGNORECASE,
    ),
)

_TOPIC_MARKERS = (
    (
        re.compile(
            r"\b(?:topics?|subjects?|modules?|units?|chapters?|syllabus|"
            r"course\s*contents?|curriculum)\b\s*(?:are|is|include|includes|:|-|–|—)?\s*",
            re.IGNORECASE,
        ),
        3,
    ),
    (
        re.compile(
            r"\b(?:covering|includes?|including|focus(?:ing)?\s+on|"
            r"consists?\s+of|made\s+up\s+of)\b\s*:?\s*",
            re.IGNORECASE,
        ),
        2,
    ),
    (
        re.compile(r"\b(?:learn(?:ing)?|study(?:ing)?|revise|revising|master(?:ing)?)\b\s+", re.IGNORECASE),
        1,
    ),
)

_GENERIC_TOPICS = {
    "introduction", "intro", "overview", "basics", "fundamentals", "general",
    "miscellaneous", "others", "practical", "practicals", "theory", "lab", "labs",
    "laboratory", "project", "projects", "assignment", "assignments", "seminar",
    "workshop", "tutorial", "tutorials", "revision", "examination", "examinations",
    "test", "tests", "quiz", "quizzes", "note", "notes", "references", "textbooks",
    "syllabus", "contents", "topics", "topic", "subject", "subjects", "unit", "units",
    "module", "modules", "chapter", "chapters", "part", "parts", "data", "information",
    "course", "curriculum", "studies",
}

_TIME_UNIT_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve)\s*(?:days?|weeks?|months?|years?|hours?|hrs?|h|minutes?|mins?)\b",
    re.IGNORECASE,
)
_TIME_CUT_RE = re.compile(
    rf"\s+(?:in|within|over|by|before|after|for|starting|from)\s+(?={_NUMBER}\s*(?:days?|weeks?|months?|years?))",
    re.IGNORECASE,
)
_TIME_AND_CUT_RE = re.compile(
    rf"\s+and\s+(?={_NUMBER}\s*(?:hours?|hrs?|h|minutes?|mins?|days?|weeks?|months?))",
    re.IGNORECASE,
)
_STUDY_CUT_RE = re.compile(
    rf"\s+(?:and\s+)?(?:studying|study|with|while\s+working)\s+"
    rf"(?={_NUMBER}\s*(?:hours?|hrs?|minutes?|mins?))",
    re.IGNORECASE,
)


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _number_value(token):
    token = (token or "").strip().lower()
    if token in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[token])
    try:
        return float(token)
    except ValueError:
        return 0.0


def _mask_timeline_noise(text):
    patterns = (
        rf"\b{_NUMBER}\s*(?:hours?|hrs?|h)\s*(?:of\s+study\s*)?"
        rf"(?:per|a|an|each|/|every)?\s*(?:study\s+)?(?:day|daily|week)\b",
        rf"\b{_NUMBER}\s*(?:minutes?|mins?|m)\s*(?:of\s+study\s*)?"
        rf"(?:per|a|an|each|/|every)?\s*(?:study\s+)?(?:day|daily|week)\b",
        rf"\b(?:\d|{_NUMBER_WORDS})\s*(?:study\s*)?days?\s*(?:per|a|an|each|/|every)\s*week\b",
    )
    masked = text
    for pattern in patterns:
        masked = re.sub(pattern, " ", masked, flags=re.IGNORECASE)
    return masked


def _extract_timeline_days(text):
    masked = _mask_timeline_noise(text)
    found = []

    for match in re.finditer(rf"\b({_NUMBER})\s*[- ]?\s*days?\b", masked, re.IGNORECASE):
        found.append(_number_value(match.group(1)))

    for match in re.finditer(rf"\b({_NUMBER})\s*[- ]?\s*weeks?\b", masked, re.IGNORECASE):
        found.append(_number_value(match.group(1)) * 7)
    for match in re.finditer(r"\bin\s+(?:a|an|one)\s+week\b", masked, re.IGNORECASE):
        found.append(7)

    for match in re.finditer(rf"\b({_NUMBER})\s*[- ]?\s*months?\b", masked, re.IGNORECASE):
        found.append(_number_value(match.group(1)) * 30)
    for match in re.finditer(r"\bin\s+(?:a|an|one)\s+month\b", masked, re.IGNORECASE):
        found.append(30)

    if not found:
        return 0
    return _clamp(int(round(max(found))), 1, 730)


def _extract_hours_per_day(text):
    match = re.search(
        rf"\b({_NUMBER})\s*(?:hours?|hrs?|h)\s*(?:of\s+study\s*)?"
        rf"(?:per|a|an|each|/|every)?\s*(?:study\s+)?(?:day|daily)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return _clamp(round(_number_value(match.group(1)), 1), 0.5, 16)

    match = re.search(
        rf"\b({_NUMBER})\s*(?:minutes?|mins?)\s*(?:of\s+study\s*)?"
        rf"(?:per|a|an|each|/|every)?\s*(?:study\s+)?(?:day|daily)\b",
        text,
        re.IGNORECASE,
    )
    if match:
        hours = round(_number_value(match.group(1)) / 60, 1)
        return _clamp(hours, 0.5, 16)

    if re.search(r"\bhalf\s+an?\s+hour\s*(?:per|a|an|each|/|every)?\s*(?:day|daily)\b", text, re.IGNORECASE):
        return 0.5
    if re.search(r"\b(?:an?|one)\s+hour\s*(?:per|a|an|each|/|every)?\s*(?:day|daily)\b", text, re.IGNORECASE):
        return 1.0
    return 0


def _extract_study_days(text):
    match = re.search(
        rf"\b(?:study(?:ing)?\s+)?(\d)\s*(?:study\s*)?days?\s*"
        rf"(?:per|a|an|each|/|every)\s*week\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return _clamp(int(match.group(1)), 1, 7)
    if re.search(r"\bweekends?\b", text, re.IGNORECASE):
        return 2
    if re.search(r"\bweekdays?\b", text, re.IGNORECASE):
        return 5
    if re.search(r"\b(?:every\s+day|daily\s+study|study\s+daily|7\s*days)\b", text, re.IGNORECASE):
        return 7
    return 0


def _extract_level(text):
    if re.search(r"\b(?:advanced|expert|experienced|professional)\b", text, re.IGNORECASE):
        return "advanced"
    if re.search(r"\b(?:intermediate|some\s+experience|working\s+knowledge)\b", text, re.IGNORECASE):
        return "intermediate"
    if re.search(
        r"\b(?:beginner|from\s+scratch|no\s+experience|absolute\s+beginner|"
        r"starting\s+from\s+zero|novice|fresher)\b",
        text,
        re.IGNORECASE,
    ):
        return "beginner"
    return ""


def _extract_pace(text):
    if re.search(r"\b(?:fast|fast-track|sprint|intense|intensive|crash|aggressive)\b", text, re.IGNORECASE):
        return "sprint"
    if re.search(r"\b(?:burnout|gentle|slow|light|relaxed|balanced|calm)\b", text, re.IGNORECASE):
        return "burnout_safe"
    if re.search(r"\b(?:steady|consistent|regular)\b", text, re.IGNORECASE):
        return "steady"
    return ""


def _extract_target_outcome(text):
    match = re.search(
        r"\b(?:so\s+i\s+can|so\s+that\s+i\s+can|goal\s+is\s+to|aim\s+is\s+to|"
        r"target\s+is\s+to|outcome\s+is\s+to)\s+"
        r"((?:get|land|find)\s+(?:a\s+)?(?:job|placement)|get\s+placed|"
        r"clear\s+(?:the\s+)?(?:exam|exams)|crack\s+(?:the\s+)?(?:exam|exams)|"
        r"pass\s+(?:the\s+)?(?:exam|exams)|build\s+(?:a\s+)?portfolio|"
        r"become\s+job[- ]ready|score\s+\d+\s*%?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    outcome = re.sub(r"\s+", " ", match.group(1)).strip(" ,.;")
    return outcome[:1].upper() + outcome[1:] if outcome else ""


def _extract_weak_areas(text):
    match = re.search(
        r"\b(?:weak\s+(?:in|at)|struggling\s+with|need\s+help\s+with|"
        r"not\s+good\s+at|improve)\s+([^.;!?]{2,120})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    weak = _strip_time_clauses(match.group(1))
    return weak.strip(" ,;")[:120]


def _strip_time_clauses(text):
    parts = []
    for part in re.split(r"[,;]", text):
        part = part.strip()
        if not part:
            continue
        if _TIME_UNIT_RE.search(part) and re.search(
            r"\b(?:in|within|over|by|before|after|for|a|an|per|each|daily|every)\b",
            part,
            re.IGNORECASE,
        ):
            continue
        parts.append(part)
    text = ", ".join(parts) if parts else text
    text = _TIME_CUT_RE.split(text, maxsplit=1)[0]
    text = _TIME_AND_CUT_RE.split(text, maxsplit=1)[0]
    text = _STUDY_CUT_RE.split(text, maxsplit=1)[0]
    return text.strip(" ,;:-–—.")


def _clean_title(text):
    text = re.sub(r"\s+", " ", text or "").strip(" ,;:-–—.")
    text = re.sub(
        r"^(?:i\s+(?:want|plan|hope|aim|need)\s+to\s+|please\s+|can\s+you\s+|"
        r"help\s+me\s+|i\s+am\s+|i'm\s+|i\s+have\s+|i've\s+got\s+|i\s+got\s+)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:create|make|build|design)\s+(?:a|an|the)?\s*"
        r"(?:study|learning|revision)?\s*(?:plan|roadmap|schedule|guide)\s+for\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:(?:study|learning|revision)\s+)?(?:plan|roadmap|schedule|guide)\s+for\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:a|an|the|my|our)\s+(?:study\s+|learning\s+|revision\s+)?"
        r"(?:plan|roadmap|schedule)\s+for\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(?:a|an|the|my|our)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:become|becoming|be)\s+(?:a|an)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\s+(?:career|career\s+path|job|role|profession|position|plan|roadmap|"
        r"preparation|prep)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip(" ,;:-–—.")
    if not text:
        return ""
    if len(text) > 80:
        text = text[:77].rstrip() + "..."
    small_words = {"and", "of", "for", "in", "on", "the", "a", "an", "to", "with", "at", "by", "from", "vs"}
    parts = text.split()
    words = []
    for index, word in enumerate(parts):
        if any(char.isupper() for char in word):
            words.append(word)
        elif word.lower() in small_words and 0 < index < len(parts) - 1:
            words.append(word.lower())
        else:
            words.append(word.capitalize())
    text = " ".join(words)
    return text


def _valid_role(role):
    role = _clean_title(role)
    if not role:
        return ""
    words = role.lower().split()
    last = words[-1].strip(".,;:!?")
    if last in _NON_ROLE_ENDINGS:
        return ""
    if not _ROLE_NOUN_RE.search(role):
        return ""
    return role


def _extract_role(text):
    for pattern in _ROLE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        role = _valid_role(match.group(1))
        if role:
            return role
    return ""


def _detect_plan_type(text, role):
    lower = text.lower()
    career_phrase = bool(
        re.search(
            r"\b(?:become|becoming|career|job|profession|work(?:ing)?\s+as|"
            r"role\s+(?:as|of)|roadmap|interview|resume|portfolio)\b",
            lower,
        )
    )
    syllabus_phrase = bool(
        re.search(
            r"\b(?:syllabus|semester|exam|exams|test|tests|paper|papers|board|"
            r"university|college|class\s+\d+|school|prelims|mains)\b",
            lower,
        )
    )
    if role and career_phrase:
        return "career"
    if syllabus_phrase:
        return "syllabus"
    if role:
        return "career"
    return "syllabus"


def _extract_title(text, role, plan_type):
    if plan_type == "career" and role:
        return role, True

    for index, pattern in enumerate(_SYLLABUS_TITLE_PATTERNS):
        match = pattern.search(text)
        if not match:
            continue
        if index == 1:
            title = f"{match.group(1)} {match.group(2)}"
        else:
            title = match.group(1)
        title = _clean_title(_strip_time_clauses(title))
        if title and not _is_time_like(title):
            return title, True

    first_sentence = re.split(r"[.!?]", text)[0]
    fallback = _clean_title(_strip_time_clauses(first_sentence))
    if fallback and _is_time_like(fallback):
        fallback = ""
    return fallback, False


def _is_time_like(item):
    if not _TIME_UNIT_RE.search(item):
        return False
    return bool(
        re.match(
            r"^(?:in|within|over|by|before|after|for|a|an|per|each|daily|every|"
            r"\d|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
            item.strip(),
            re.IGNORECASE,
        )
    )


def _split_topic_text(text):
    text = re.sub(r"\betc\.?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:and|&)\s+", ", ", text)
    raw_parts = re.split(r"[,;•·\n]+", text)
    topics = []
    seen = set()
    for part in raw_parts:
        item = re.sub(r"\s+", " ", part).strip(" .;:-–—")
        item = re.sub(
            r"^(?:topics?|subjects?|modules?|units?|chapters?|like|such\s+as|"
            r"e\.g\.?|i\.e\.?|including|the|a|an|my|our)\s+",
            "",
            item,
            flags=re.IGNORECASE,
        )
        item = re.sub(r"^(?:and|&)\s+", "", item, flags=re.IGNORECASE)
        item = item.strip(" .;:-–—")
        if not item or len(item) < 3 or len(item) > 140:
            continue
        if not re.search(r"[A-Za-z]{2}", item):
            continue
        if re.match(
            r"^(?:weak\s+(?:in|at)|struggling\s+with|need\s+help\s+with|"
            r"not\s+good\s+at|improve)\b",
            item,
            re.IGNORECASE,
        ):
            continue
        lower = item.lower()
        if lower in _GENERIC_TOPICS:
            continue
        if _is_time_like(item):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", lower).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        topics.append(item)
        if len(topics) >= 80:
            break
    return topics


def _extract_topics(text):
    best_topics = []
    best_score = 0
    for pattern, weight in _TOPIC_MARKERS:
        for match in pattern.finditer(text):
            tail = text[match.end():]
            tail = re.split(r"[.!?]\s+|[.!?]$", tail)[0]
            tail = _TIME_CUT_RE.split(tail, maxsplit=1)[0]
            tail = _TIME_AND_CUT_RE.split(tail, maxsplit=1)[0]
            tail = _STUDY_CUT_RE.split(tail, maxsplit=1)[0]
            tail = tail.split("\n")[0]
            if re.match(
                rf"^(?:{_NUMBER}\s*(?:hours?|hrs?|h|minutes?|mins?|days?|weeks?|months?)|"
                rf"(?:a|an|one)\s+(?:hour|day|week|month))\b",
                tail.strip(),
                re.IGNORECASE,
            ):
                continue
            candidates = _split_topic_text(tail)
            if not candidates:
                continue
            score = weight * 100 + len(candidates)
            if score > best_score:
                best_score = score
                best_topics = candidates
    return best_topics


def parse_plan_text(text):
    """Return roadmap form values understood from free-form text."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if not raw:
        return {
            "title": "",
            "roadmap_type": "syllabus",
            "plan_days": 0,
            "timeline_weeks": 0,
            "hours_per_day": 0,
            "study_days_per_week": 0,
            "current_level": "",
            "pace_mode": "",
            "target_outcome": "",
            "weak_areas": "",
            "topics": [],
            "summary": [],
            "notes": ["Describe your goal, timeline, daily hours, or topics to fill the form."],
            "understood": False,
        }

    role = _extract_role(raw)
    plan_type = _detect_plan_type(raw, role)
    title, title_matched = _extract_title(raw, role, plan_type)
    plan_days = _extract_timeline_days(raw)
    hours_per_day = _extract_hours_per_day(raw)
    study_days = _extract_study_days(raw)
    level = _extract_level(raw)
    pace = _extract_pace(raw)
    outcome = _extract_target_outcome(raw)
    weak_areas = _extract_weak_areas(raw)
    topics = _extract_topics(raw)

    understood = bool(
        role
        or title_matched
        or plan_days
        or hours_per_day
        or study_days
        or level
        or pace
        or outcome
        or weak_areas
        or topics
    )
    if not understood:
        title = ""

    notes = []
    if re.search(r"\b(?:upsc|civil\s+services|ias)\b", raw, re.IGNORECASE):
        notes.append(
            "UPSC plans work best in the dedicated UPSC Mission builder, with PYQ mocks and materials."
        )
    if plan_type == "syllabus" and not topics:
        notes.append("No topic list found. Add your modules in the syllabus box below before saving.")
    if not plan_days:
        notes.append("No timeline found. Leave days at 0 to auto-estimate from your topics and hours.")

    summary = ["Career plan" if plan_type == "career" else "Study plan"]
    if title:
        summary.append(title)
    if plan_days:
        summary.append(f"{plan_days} days")
    if hours_per_day:
        summary.append(f"{hours_per_day:g} {'hr' if hours_per_day == 1 else 'hrs'}/day")
    if study_days:
        summary.append(f"{study_days} study days/week")
    if level:
        summary.append(level.capitalize())
    if pace:
        summary.append({"sprint": "Fast-track", "burnout_safe": "Burnout-safe", "steady": "Steady"}[pace])
    if topics:
        summary.append(f"{len(topics)} {'topic' if len(topics) == 1 else 'topics'}")
    if outcome:
        summary.append(outcome)
    if weak_areas:
        summary.append(f"Focus: {weak_areas}")

    if not understood:
        notes.insert(0, "I couldn't find a goal or schedule there. Try: \"Data analyst in 3 months, 2 hours a day\".")

    return {
        "title": title,
        "roadmap_type": plan_type,
        "plan_days": plan_days,
        "timeline_weeks": max(1, round(plan_days / 7)) if plan_days else 0,
        "hours_per_day": hours_per_day,
        "study_days_per_week": study_days,
        "current_level": level,
        "pace_mode": pace,
        "target_outcome": outcome,
        "weak_areas": weak_areas,
        "topics": topics,
        "summary": summary,
        "notes": notes,
        "understood": understood,
    }
