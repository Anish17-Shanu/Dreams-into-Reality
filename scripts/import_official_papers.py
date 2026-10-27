"""Import an official UPSC paper into the local PYQ cache.

Examples (from the project root):

    # Mains paper with a text layer
    .venv/Scripts/python.exe scripts/import_official_papers.py \
        --stage mains --year 2024 --paper GS-I \
        --pdf instance/official/mains2024_gs1.pdf

    # Scanned prelims paper plus OCR text and the official key
    .venv/Scripts/python.exe scripts/import_official_papers.py \
        --stage prelims --year 2024 \
        --text-file instance/official/prelims2024_ocr.txt \
        --key-file instance/official/prelims2024_key.txt --set A

    # Check parsing without writing to the database
    ... --dry-run --json-out instance/official/parsed.json

No network, LLM, or paid service is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models.models import Question  # noqa: E402
from pyq.bank import _normalized_key  # noqa: E402
from pyq.official_pdf import (  # noqa: E402
    MAINS_MIN_QUESTIONS,
    OFFICIAL_PYQ_URL,
    PRELIMS_MIN_QUESTIONS,
    OfficialPaperError,
    build_records,
    extract_pdf_text,
    load_paper_text,
)


def _load_key_text(path):
    if not path:
        return None
    if path.lower().endswith(".pdf"):
        return extract_pdf_text(path)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    if len(text.strip()) < 10:
        raise OfficialPaperError(f"{path} does not contain an answer key.", code="empty_key")
    return text


def _upsert(records):
    existing_by_id = {
        row.external_id: row
        for row in Question.query.filter(Question.external_id.like("official:%")).all()
    }
    existing_by_text = {}
    for row in Question.query.all():
        if row.question_text:
            existing_by_text.setdefault(_normalized_key(row.question_text), row)

    created = 0
    upgraded = 0
    for record in records:
        row = existing_by_id.get(record["external_id"])
        if row is None:
            row = existing_by_text.get(_normalized_key(record["question_text"]))
            if row is not None:
                # The same question already exists from a public archive.
                # Promote it to the official verification tier instead of
                # creating a duplicate that would appear twice in tests.
                row.verification = record["verification"]
                row.source_name = record["source_name"]
                row.source_url = OFFICIAL_PYQ_URL
                row.quality_score = max(row.quality_score or 0.0, record["quality_score"])
                if record["stage"] == "prelims":
                    row.options_json = record["options_json"]
                    row.correct_answer = record["correct_answer"]
                if record["stage"] == "mains" and not row.answer_text:
                    row.answer_text = record["answer_text"]
                upgraded += 1
                continue
            row = Question(**record)
            db.session.add(row)
            existing_by_text[_normalized_key(record["question_text"])] = row
            created += 1
            continue
        for field, value in record.items():
            setattr(row, field, value)

    db.session.commit()
    return {"created": created, "upgraded": upgraded}


def _summarize(result):
    print(
        f"{result['stage']} {result['year']}"
        + (f" {result['paper']}" if result.get("paper") else "")
        + f": parsed {result['parsed_blocks']} blocks, "
        f"{len(result['records'])} valid records"
        + (f", {result['answer_count']} keys" if result["stage"] == "prelims" else "")
    )
    if result["rejected"]:
        print(f"  rejected: {result['rejected']}")
    if result["missing_keys"]:
        preview = ", ".join(str(item) for item in result["missing_keys"][:15])
        print(f"  missing keys: {preview}{' ...' if len(result['missing_keys']) > 15 else ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("prelims", "mains"))
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--paper", default="GS-I", help="Mains paper: GS-I, GS-II, GS-III")
    parser.add_argument("--pdf", help="Official question paper PDF")
    parser.add_argument("--text-file", help="UTF-8 OCR or extracted text of the paper")
    parser.add_argument("--key-file", help="Official answer key text or PDF")
    parser.add_argument("--set", dest="key_set", choices=("A", "B", "C", "D"))
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write")
    parser.add_argument("--allow-partial", action="store_true", help="Accept an incomplete paper")
    parser.add_argument("--json-out", help="Write the parsed records to this JSON file")
    args = parser.parse_args()

    if args.year < 2013 or args.year > 2030:
        raise SystemExit("--year looks wrong; expected 2013-2030.")
    if args.stage == "prelims" and not (args.key_file):
        if not args.dry_run:
            raise SystemExit(
                "Prelims imports need the official answer key: pass --key-file "
                "(a text/PDF key or a plain '1 b' list)."
            )

    try:
        text = load_paper_text(pdf_path=args.pdf, text_path=args.text_file)
        key_text = _load_key_text(args.key_file) if args.key_file else None
        result = build_records(
            text,
            args.stage,
            args.year,
            paper=args.paper,
            key_text=key_text,
            key_set=args.key_set,
        )
    except OfficialPaperError as exc:
        raise SystemExit(f"[{exc.code}] {exc}") from exc

    _summarize(result)
    if args.json_out:
        payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        with open(args.json_out, "w", encoding="utf-8") as handle:
            handle.write(payload)
        print(f"  parsed records written to {args.json_out}")

    minimum = PRELIMS_MIN_QUESTIONS if args.stage == "prelims" else MAINS_MIN_QUESTIONS
    if not args.allow_partial and len(result["records"]) < minimum:
        raise SystemExit(
            f"Only {len(result['records'])} valid records (minimum {minimum}). "
            "Check the OCR text/layout or pass --allow-partial deliberately."
        )
    if args.stage == "prelims" and result["missing_keys"] and not args.allow_partial:
        limit = max(5, int(round(result["parsed_blocks"] * 0.1)))
        if len(result["missing_keys"]) > limit:
            raise SystemExit(
                f"{len(result['missing_keys'])} questions have no answer key. "
                "Fix the key file or pass --allow-partial."
            )

    if args.dry_run:
        print("Dry run: no database changes.")
        return

    with app.app_context():
        counts = _upsert(result["records"])
    print(
        f"Imported {len(result['records'])} records: "
        f"{counts['created']} created, {counts['upgraded']} archive rows upgraded."
    )


if __name__ == "__main__":
    main()
