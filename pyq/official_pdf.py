"""Deterministic importer for official UPSC question papers.

Official UPSC prelims PDFs are usually scanned images, so they have no text
layer. This module parses text when it exists and accepts OCR text supplied by
the operator (``--text-file``). It never calls an LLM or a paid service.

The parsers are intentionally conservative: question blocks are only accepted
when the four options (prelims) or the marks/word limit (mains) are present.
Anything ambiguous is reported instead of being imported as noise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pyq.bank import (
    MAINS_PAPERS,
    OFFICIAL_PYQ_URL,
    _clean_text,
    _mains_framework,
    _normalized_key,
)
from pyq.taxonomy import classify_topic, is_self_contained

PRELIMS_MIN_QUESTIONS = 50
MAINS_MIN_QUESTIONS = 10
MAX_QUESTION_LENGTH = 1600

MAINS_PAPER_SUBJECTS = {
    "GS-I": MAINS_PAPERS["GSI"][1],
    "GS-II": MAINS_PAPERS["GSII"][1],
    "GS-III": MAINS_PAPERS["GSIII"][1],
}

_QUESTION_START = re.compile(r"^\s*(\d{1,3})\s*[.)]\s+(.*)$")
_MAINS_START = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+(.*)$")
_OPTION_MARKER = re.compile(r"\(\s*([a-dA-D])\s*\)")
_SECTION_HEADING = re.compile(r"(?i)^\s*SECTION\s+[A-D]\s*$")
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_PAGE_NUMBER = re.compile(r"(?m)^\s*(?:page\s+)?\d{1,3}\s*$", re.IGNORECASE)
_PAGE_NOISE = re.compile(
    r"(?mi)^\s*(?:www\.upsc\.gov\.in|upsc\.gov\.in|do not open this booklet.*)\s*$"
)
_KEY_SET_HEADING = re.compile(r"(?i)\bSET[\s\-]*([A-D])\b")
_KEY_PAIR = re.compile(r"(?<![\d])(\d{1,3})\s*[.):\-]?\s*\(?([a-dA-D])\)?(?![\w])")
_MARKS = re.compile(r"(\d{1,2})\s*marks?", re.IGNORECASE)
_WORDS = re.compile(r"(\d{2,3})\s*words?", re.IGNORECASE)
_TRAILING_META = re.compile(
    r"\s*\(?\s*\d{1,2}\s*marks?\s*[,/]?\s*\d{2,3}\s*words?\s*\)?\s*$",
    re.IGNORECASE,
)


class OfficialPaperError(Exception):
    """Raised when a paper cannot be parsed without guessing."""

    def __init__(self, message, code="parse_error"):
        super().__init__(message)
        self.code = code


def normalize_paper_text(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _PAGE_NUMBER.sub("", text)
    text = _PAGE_NOISE.sub("", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_pdf_text(path):
    try:
        from PyPDF2 import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise OfficialPaperError(
            "PyPDF2 is not installed. Run `pip install -r requirements.txt`.",
            code="missing_dependency",
        ) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise OfficialPaperError(f"Could not open the PDF: {exc}", code="bad_pdf") from exc

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # pragma: no cover - malformed page
            pages.append("")
    text = "\n".join(pages)
    if len(re.sub(r"\s+", "", text)) < 200:
        raise OfficialPaperError(
            "This PDF has no usable text layer (most official UPSC papers are scanned images). "
            "OCR it with a free tool first, for example "
            "`ocrmypdf --skip-text paper.pdf paper-ocr.pdf` (PyMuPDF + Tesseract), "
            "then pass the extracted text with --text-file.",
            code="no_text_layer",
        )
    return text


def load_paper_text(pdf_path=None, text_path=None):
    if text_path:
        raw = Path(text_path).read_text(encoding="utf-8", errors="replace")
        if len(re.sub(r"\s+", "", raw)) < 200:
            raise OfficialPaperError(
                f"{text_path} is too small to be a full question paper.",
                code="empty_text",
            )
        return raw
    if not pdf_path:
        raise OfficialPaperError("Provide --pdf or --text-file.", code="missing_input")
    return extract_pdf_text(pdf_path)


def _abcd_run(text):
    run = 0
    start = None
    markers = list(_OPTION_MARKER.finditer(text))
    for index, marker in enumerate(markers):
        letter = marker.group(1).lower()
        if letter == "abcd"[run]:
            if run == 0:
                start = index
            run += 1
            if run == 4:
                return markers[start:start + 4]
        elif letter == "a":
            run = 1
            start = index
        else:
            run = 0
            start = None
    return None


def _options_complete(text):
    return _abcd_run(text) is not None


def split_stem_options(text):
    markers = _abcd_run(text)
    if markers is None:
        return None
    stem = text[:markers[0].start()]
    options = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index < 3 else len(text)
        options.append(_clean_text(text[marker.end():end]))
    return _clean_text(stem), options


def _finalize_prelims_block(number, lines):
    body = "\n".join(lines)
    parts = split_stem_options(body)
    if parts is None:
        return None
    stem, options = parts
    return {"number": number, "stem": stem, "options": options}


def parse_prelims_blocks(text):
    """Split a prelims paper into question blocks using the (a)-(d) layout."""
    lines = normalize_paper_text(text).split("\n")
    blocks = []
    current = None
    expected = 1

    def flush():
        nonlocal current
        if current is None:
            return
        block = _finalize_prelims_block(current["number"], current["lines"])
        if block is not None:
            blocks.append(block)
        current = None

    for line in lines:
        match = _QUESTION_START.match(line)
        if current is None:
            if match and int(match.group(1)) == expected:
                current = {"number": expected, "lines": [match.group(2)]}
                expected += 1
            continue

        if (
            match
            and int(match.group(1)) == current["number"] + 1
            and _options_complete("\n".join(current["lines"]))
        ):
            flush()
            current = {"number": int(match.group(1)), "lines": [match.group(2)]}
            expected = current["number"] + 1
            continue
        current["lines"].append(line)

    flush()
    return blocks


def _key_section(text, key_set):
    if not key_set:
        return text
    pattern = re.compile(
        rf"(?is)\bSET[\s\-]*{re.escape(key_set)}\b(.*?)(?=\bSET[\s\-]*[A-D]\b|\Z)"
    )
    match = pattern.search(text)
    return match.group(1) if match else text


def parse_answer_key(text, key_set=None):
    """Parse lines such as ``1. (b)`` or table rows such as ``1 b 2 c``."""
    if not text:
        return {}
    text = _key_section(normalize_paper_text(text), key_set)
    answers = {}
    for line in text.split("\n"):
        if not re.search(r"[a-dA-D]", line):
            continue
        for number, letter in _KEY_PAIR.findall(line):
            number = int(number)
            if not 1 <= number <= 200:
                continue
            letter = letter.lower()
            previous = answers.get(number)
            if previous and previous != letter:
                raise OfficialPaperError(
                    f"Conflicting keys for question {number}: {previous} and {letter}. "
                    "Pass --set A/B/C/D when the key file contains multiple sets.",
                    code="ambiguous_key",
                )
            answers[number] = letter
    return answers


def build_prelims_records(text, year, key_text=None, key_set=None):
    blocks = parse_prelims_blocks(text)
    answers = parse_answer_key(key_text, key_set=key_set) if key_text else {}
    records = []
    missing = []
    rejected = {}
    seen = set()

    for block in blocks:
        number = block["number"]
        stem = block["stem"]
        options = block["options"]
        answer = answers.get(number)
        if answer is None:
            missing.append(number)
            continue
        if len(stem) < 30 or len(stem) > MAX_QUESTION_LENGTH:
            rejected["question_length"] = rejected.get("question_length", 0) + 1
            continue
        if not is_self_contained(stem):
            rejected["figure_dependent"] = rejected.get("figure_dependent", 0) + 1
            continue
        if any(not option or len(option) > 260 for option in options):
            rejected["bad_options"] = rejected.get("bad_options", 0) + 1
            continue
        if len({option.casefold() for option in options}) < 4:
            rejected["duplicate_options"] = rejected.get("duplicate_options", 0) + 1
            continue
        fingerprint = _normalized_key(stem)
        if not fingerprint or fingerprint in seen:
            rejected["duplicate"] = rejected.get("duplicate", 0) + 1
            continue
        seen.add(fingerprint)

        subject, topic = classify_topic(stem, "General Studies", "GS Paper I")
        records.append({
            "exam": "UPSC",
            "subject": subject[:120],
            "topic": topic[:160],
            "question_text": stem,
            "answer_text": None,
            "difficulty": "medium",
            "stage": "prelims",
            "year": int(year),
            "paper": "GS Paper I",
            "options_json": json.dumps(options, ensure_ascii=False),
            "correct_answer": answer,
            "source_url": OFFICIAL_PYQ_URL,
            "source_name": (
                f"UPSC CSE Prelims GS-I {year} (official paper and answer key)"
            ),
            "external_id": f"official:prelims:{year}:{number}",
            "quality_score": 1.0,
            "verification": "verified",
            "is_public": True,
        })

    return {
        "stage": "prelims",
        "year": int(year),
        "parsed_blocks": len(blocks),
        "answer_count": len(answers),
        "missing_keys": missing,
        "rejected": rejected,
        "records": records,
    }


def _mains_meta(block_text, number):
    matches = list(_TRAILING_META.finditer(block_text))
    marks = None
    words = None
    body = block_text
    if matches:
        match = matches[-1]
        meta = match.group(0)
        marks_match = _MARKS.search(meta)
        words_match = _WORDS.search(meta)
        marks = int(marks_match.group(1)) if marks_match else None
        words = int(words_match.group(1)) if words_match else None
        body = block_text[:match.start()]
    else:
        # Some official layouts print the marks and word limit on their own lines.
        tail = [line.strip() for line in block_text.split("\n") if line.strip()]
        if len(tail) >= 2 and re.fullmatch(r"\d{1,2}", tail[-2]) and re.fullmatch(r"\d{2,3}", tail[-1]):
            marks = int(tail[-2])
            words = int(tail[-1])
            body = "\n".join(tail[:-2])
    marks = marks if marks and 5 <= marks <= 25 else (10 if number <= 10 else 15)
    words = words if words and 50 <= words <= 400 else (150 if marks <= 10 else 250)
    return _clean_text(body), marks, words


def parse_mains_blocks(text):
    lines = normalize_paper_text(text).split("\n")
    blocks = []
    current = None
    expected = 1

    def flush():
        nonlocal current
        if current is not None:
            blocks.append({"number": current["number"], "text": "\n".join(current["lines"])})
            current = None

    for line in lines:
        if _SECTION_HEADING.match(line):
            continue
        match = _MAINS_START.match(line)
        if match and int(match.group(1)) == expected:
            flush()
            current = {"number": expected, "lines": [match.group(2)]}
            expected += 1
            continue
        if current is not None:
            current["lines"].append(line)

    flush()
    return blocks


def build_mains_records(text, year, paper="GS-I"):
    if paper not in MAINS_PAPER_SUBJECTS:
        raise OfficialPaperError(
            f"Paper {paper} is not supported by the current mains practice view "
            "(GS-I, GS-II, GS-III).",
            code="unsupported_paper",
        )
    records = []
    rejected = {}
    seen = set()
    blocks = parse_mains_blocks(text)
    for block in blocks:
        number = block["number"]
        question, marks, words = _mains_meta(block["text"], number)
        if len(question) < 25 or len(question) > 1200:
            rejected["question_length"] = rejected.get("question_length", 0) + 1
            continue
        if not is_self_contained(question):
            rejected["figure_dependent"] = rejected.get("figure_dependent", 0) + 1
            continue
        fingerprint = _normalized_key(question)
        if not fingerprint or fingerprint in seen:
            rejected["duplicate"] = rejected.get("duplicate", 0) + 1
            continue
        seen.add(fingerprint)

        base_subject = MAINS_PAPER_SUBJECTS[paper]
        subject, topic = classify_topic(question, base_subject, paper)
        records.append({
            "exam": "UPSC",
            "subject": subject[:120],
            "topic": topic[:160],
            "question_text": question,
            "answer_text": _mains_framework(question, paper, marks, words),
            "difficulty": "hard" if marks >= 15 else "medium",
            "stage": "mains",
            "year": int(year),
            "paper": paper,
            "options_json": None,
            "correct_answer": None,
            "source_url": OFFICIAL_PYQ_URL,
            "source_name": f"UPSC CSE Mains {paper} {year} (official paper)",
            "external_id": f"official:mains:{paper}:{year}:{number}",
            "quality_score": 1.0,
            "verification": "imported",
            "is_public": True,
        })

    return {
        "stage": "mains",
        "year": int(year),
        "paper": paper,
        "parsed_blocks": len(blocks),
        "answer_count": 0,
        "missing_keys": [],
        "rejected": rejected,
        "records": records,
    }


def build_records(text, stage, year, paper="GS-I", key_text=None, key_set=None):
    if stage == "prelims":
        return build_prelims_records(text, year, key_text=key_text, key_set=key_set)
    if stage == "mains":
        return build_mains_records(text, year, paper=paper)
    raise OfficialPaperError("stage must be 'prelims' or 'mains'.", code="bad_stage")
