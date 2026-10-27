"""Export a validated PYQ database into the bundled seed fixture.

Usage (from the project root, pointed at any populated database):

    DATABASE_URL=sqlite:///e2e.sqlite3 AUTO_CREATE_SCHEMA=true PYQ_SEED_ENABLED=false \
        .venv/Scripts/python.exe scripts/export_pyq_seed.py

The output is a deterministic gzip JSON file used by ``pyq.seed.seed_bank``.
No network or LLM is involved.
"""

from __future__ import annotations

import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models.models import Question  # noqa: E402
from pyq.taxonomy import classify_topic, is_self_contained  # noqa: E402

OUTPUT = os.path.join(app.config["BASE_DIR"], "pyq", "seed", "upsc_bank.json.gz")

FIELDS = (
    "exam",
    "subject",
    "topic",
    "question_text",
    "answer_text",
    "difficulty",
    "stage",
    "year",
    "paper",
    "options_json",
    "correct_answer",
    "source_url",
    "source_name",
    "external_id",
    "quality_score",
    "verification",
)


def _verification(row):
    value = getattr(row, "verification", None)
    if value in {"verified", "imported", "archive"}:
        return value
    source = (row.source_name or "").lower()
    if "official key verified" in source and "not officially" not in source:
        return "verified"
    if row.stage == "mains":
        return "archive"
    return "archive"


def build_records():
    rows = (
        Question.query.filter(
            Question.stage.in_(("prelims", "mains")),
            Question.is_public.is_(True),
        )
        .order_by(Question.stage.asc(), Question.year.asc(), Question.external_id.asc())
        .all()
    )
    records = []
    skipped = 0
    for row in rows:
        if not row.external_id or not row.question_text:
            skipped += 1
            continue
        if not is_self_contained(row.question_text):
            skipped += 1
            continue
        subject, topic = classify_topic(row.question_text, row.subject, row.topic)
        record = {field: getattr(row, field, None) for field in FIELDS}
        record["subject"] = subject[:120] if subject else row.subject
        record["topic"] = topic[:160] if topic else row.topic
        record["verification"] = _verification(row)
        record["is_public"] = True
        records.append(record)
    return records, skipped


def main():
    with app.app_context():
        records, skipped = build_records()
        if not records:
            raise SystemExit("No public PYQ rows found. Point DATABASE_URL at a populated database.")
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        payload = json.dumps(records, ensure_ascii=False, sort_keys=True).encode("utf-8")
        with open(OUTPUT, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
                handle.write(payload)
        prelims = sum(1 for item in records if item["stage"] == "prelims")
        mains = len(records) - prelims
        print(
            f"Wrote {len(records)} PYQs ({prelims} prelims, {mains} mains) to {OUTPUT} "
            f"({len(payload)} bytes raw, skipped {skipped})"
        )


if __name__ == "__main__":
    main()
