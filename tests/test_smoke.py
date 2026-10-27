import os
import re
import shutil
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

_TEST_ROOT = tempfile.mkdtemp(prefix="dir-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEST_ROOT, 'test.sqlite3').as_posix()}"
os.environ["AUTO_CREATE_SCHEMA"] = "false"
os.environ["AUTO_FETCH_RESOURCES_ON_CREATE"] = "false"
os.environ["ENABLE_EXTERNAL_RESOURCES"] = "false"
os.environ["PYQ_SYNC_ENABLED"] = "false"

from app import app
from extensions import db
from models.models import (
    PyqSyncState,
    Question,
    QuizQuestion,
    QuizResult,
    Roadmap,
    Task,
    User,
)
from pyq.bank import _http_get_json, _validate_prelims_item, coverage_stats
from pyq.official_pdf import (
    OfficialPaperError,
    build_mains_records,
    build_prelims_records,
    extract_pdf_text,
    parse_answer_key,
)
from pyq.seed import _read_seed, seed_available
from pyq.service import prelims_questions
from pyq.taxonomy import classify_topic, is_self_contained
from dashboard.nl_plan import parse_plan_text
from dashboard.routes import _extract_topics_with_stats, _study_dates

unittest.addModuleCleanup(shutil.rmtree, _TEST_ROOT, ignore_errors=True)

FAKE_STATS = {
    "prelims_total": 250,
    "mains_total": 120,
    "by_year": {2020: 100, 2021: 150},
    "years": [2020, 2021],
    "prelims_state": None,
    "mains_state": None,
    "last_synced_at": None,
    "refresh_days": 7,
    "attribution": "test",
    "official_url": "https://www.upsc.gov.in/",
    "answer_key_url": "https://www.upsc.gov.in/",
}


def fake_prelims_questions(amount=10, **kwargs):
    return [
        {
            "id": index + 1,
            "stage": "prelims",
            "question": f"Practice PYQ {index + 1}: which statement about polity is correct?",
            "options": [
                "Statement one is correct",
                "Statement two is correct",
                "Both are correct",
                "Neither is correct",
            ],
            "correct": "a",
            "subject": "Polity",
            "topic": "Constitution",
            "year": 2020,
            "paper": "GS Paper I",
            "difficulty": "medium",
            "source": "UPSC CSE Prelims GS-I",
            "source_url": "https://www.upsc.gov.in/",
        }
        for index in range(amount)
    ]


class DreamsIntoRealityTests(unittest.TestCase):
    def setUp(self):
        self.upload_dir = tempfile.mkdtemp(prefix="dir-uploads-")
        app.config.update(
            TESTING=True,
            AUTO_CREATE_SCHEMA=False,
            ENABLE_EXTERNAL_RESOURCES=False,
            PYQ_SYNC_ENABLED=False,
            AUTO_FETCH_RESOURCES_ON_CREATE=False,
            SESSION_COOKIE_SECURE=False,
            RATELIMIT_ENABLED=False,
            ORIGIN_CHECK_ENABLED=True,
            UPLOAD_FOLDER=self.upload_dir,
        )
        self.client = app.test_client()

        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(self.upload_dir, ignore_errors=True)

    def _register_and_login(self, email="owner@example.com", password="StrongPass1"):
        self.client.post(
            "/register",
            data={"email": email, "password": password},
            follow_redirects=True,
        )
        response = self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def _create_roadmap(self, path="/roadmap/new", **overrides):
        payload = {
            "title": "Math Sprint",
            "roadmap_type": "syllabus",
            "source_text": "Unit 1: Algebra\nUnit 2: Calculus",
            "confirmed_topics": "Algebra\nCalculus",
            "timeline_weeks": "4",
            "hours_per_week": "6",
            "study_days_per_week": "5",
            "pace_mode": "steady",
        }
        payload.update(overrides)
        return self.client.post(path, data=payload, follow_redirects=False)

    def _create_upsc_roadmap(self):
        response = self.client.post(
            "/upsc/new",
            data={
                "title": "UPSC System",
                "upsc_focus": "full_journey",
                "plan_days": "60",
                "hours_per_day": "3",
                "study_days_per_week": "6",
                "pace_mode": "steady",
                "start_date": "2026-11-02",
                "confirmed_topics": "UPSC exam strategy and attempt planning\nNCERT foundation build-up",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        return int(response.headers["Location"].rsplit("/", 1)[-1])

    def test_register_rejects_weak_password(self):
        response = self.client.post(
            "/register",
            data={"email": "owner@example.com", "password": "short"},
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Use at least 8 characters", body)
        with app.app_context():
            self.assertIsNone(User.query.filter_by(email="owner@example.com").first())

    def test_days_and_hours_shape_the_plan(self):
        self._register_and_login()
        response = self._create_roadmap(
            plan_days="30",
            hours_per_day="2",
            study_days_per_week="5",
            start_date="2026-11-02",
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            roadmap = Roadmap.query.one()
            self.assertEqual(roadmap.plan_days, 30)
            self.assertAlmostEqual(roadmap.hours_per_day, 2.0)
            self.assertEqual(roadmap.hours_per_week, 10)
            self.assertEqual(roadmap.start_date, date(2026, 11, 2))
            self.assertGreaterEqual(roadmap.target_date, date(2026, 11, 30))
            tasks = Task.query.filter_by(roadmap_id=roadmap.id).all()
            self.assertTrue(tasks)
            self.assertTrue(all(task.due_date.weekday() < 5 for task in tasks))

        view = self.client.get(response.headers["Location"], follow_redirects=True)
        body = view.get_data(as_text=True)
        self.assertEqual(view.status_code, 200)
        self.assertIn("Your plan at a glance", body)
        self.assertIn("2.0 hrs/day", body)
        self.assertIn("Plan window", body)

    def test_study_dates_skip_rest_days(self):
        dates = _study_dates(date(2026, 11, 2), 14, 5)
        self.assertTrue(dates)
        self.assertTrue(all(day.weekday() < 5 for day in dates))
        self.assertEqual(min(dates), date(2026, 11, 2))
        self.assertLessEqual(max(dates), date(2026, 11, 2) + timedelta(days=13))

    def test_cross_site_post_is_rejected(self):
        response = self.client.post(
            "/login",
            data={"email": "owner@example.com", "password": "StrongPass1"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 403)

    def test_rate_limits_repeat_login_attempts(self):
        app.config["RATELIMIT_ENABLED"] = True
        try:
            statuses = []
            for _ in range(11):
                response = self.client.get(
                    "/login", environ_base={"REMOTE_ADDR": "203.0.113.77"}
                )
                statuses.append(response.status_code)
            self.assertEqual(statuses[:10], [200] * 10)
            self.assertEqual(statuses[10], 429)
        finally:
            app.config["RATELIMIT_ENABLED"] = False

    def test_health_endpoint_reports_database(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["database"], "up")

    def test_view_roadmap_degrades_if_optional_tables_are_missing(self):
        self._register_and_login()
        create_response = self._create_roadmap(
            title="Career Clarity",
            roadmap_type="career",
            confirmed_topics="",
            source_text="",
            timeline_weeks="6",
            hours_per_week="6",
            study_days_per_week="5",
        )
        self.assertEqual(create_response.status_code, 302)

        with patch("dashboard.routes._has_table", side_effect=lambda name: name not in {"mock_test_schedule", "quiz_result", "question_attempt", "pyq_completion"}):
            response = self.client.get(create_response.headers["Location"], follow_redirects=True)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Career Clarity", body)

    def test_career_title_only_generates_topics_projects_and_assignments(self):
        self._register_and_login()
        response = self.client.post(
            "/roadmap/new",
            data={
                "title": "Marine Biologist",
                "roadmap_type": "career",
                "plan_days": "30",
                "hours_per_day": "2",
                "study_days_per_week": "5",
                "pace_mode": "steady",
                "current_level": "beginner",
                "start_date": datetime.now(UTC).date().isoformat(),
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            roadmap = Roadmap.query.one()
            titles = [task.title for task in Task.query.filter_by(roadmap_id=roadmap.id).all()]
            self.assertGreaterEqual(len(titles), 20)
            self.assertGreaterEqual(len([title for title in titles if title.startswith("Project:")]), 3)
            self.assertGreaterEqual(len([title for title in titles if title.startswith("Assignment:")]), 4)
            self.assertIn("Career Family", roadmap.source_text)
            self.assertIn("Career Toolkit", roadmap.source_text)
            self.assertIn("Science and research", roadmap.source_text)

        view = self.client.get(response.headers["Location"], follow_redirects=True)
        body = view.get_data(as_text=True)
        self.assertEqual(view.status_code, 200)
        self.assertIn("Career Outcome System", body)
        self.assertIn("Path context", body)
        self.assertIn("Assignment Tracker", body)
        self.assertIn("Your current title", body)

    def test_completing_a_task_keeps_the_roadmap_view_working(self):
        self._register_and_login()
        response = self._create_roadmap(
            confirmed_topics="\n".join(f"Practice topic {index}" for index in range(1, 11)),
        )
        roadmap_id = int(response.headers["Location"].rsplit("/", 1)[-1])
        with app.app_context():
            task = Task.query.filter_by(roadmap_id=roadmap_id).order_by(Task.order_index.asc()).first()
            task_id = task.id

        update = self.client.post(
            f"/roadmap/{roadmap_id}/task/{task_id}/status",
            data={"status": "done", "completion_type": "planned"},
            follow_redirects=True,
        )
        body = update.get_data(as_text=True)
        self.assertEqual(update.status_code, 200)
        self.assertIn("Momentum Starter", body)
        self.assertIn("First Step", body)

    def test_titles_and_badges_react_to_delays_and_completion(self):
        self._register_and_login()
        start = datetime.now(UTC).date() - timedelta(days=10)
        response = self._create_roadmap(
            confirmed_topics="\n".join(f"Practice topic {index}" for index in range(1, 11)),
            plan_days="20",
            hours_per_day="1",
            study_days_per_week="5",
            start_date=start.isoformat(),
        )
        self.assertEqual(response.status_code, 302)
        roadmap_id = int(response.headers["Location"].rsplit("/", 1)[-1])

        with app.app_context():
            tasks = Task.query.filter_by(roadmap_id=roadmap_id).order_by(Task.order_index.asc()).all()
            self.assertGreaterEqual(len(tasks), 6)
            for task in tasks[:6]:
                task.due_date = datetime.now(UTC).date() - timedelta(days=3)
                task.status = "todo"
            db.session.commit()

        delayed = self.client.get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Momentum at Risk", delayed)
        self.assertIn("Overdue Stack", delayed)

        with app.app_context():
            tasks = Task.query.filter_by(roadmap_id=roadmap_id).all()
            for task in tasks:
                task.status = "done"
                task.completed_at = datetime.now(UTC).replace(tzinfo=None)
            roadmap = db.session.get(Roadmap, roadmap_id)
            roadmap.completed_tasks = len(tasks)
            db.session.commit()

        recovered = self.client.get("/dashboard", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Roadmap Finisher", recovered)
        self.assertIn("Halfway Hero", recovered)
        self.assertNotIn("Overdue Stack", recovered)

    def test_syllabus_extraction_keeps_topics_and_drops_admin_noise(self):
        text = """
        BCA (Hons.) Semester IV
        Department of Computer Science
        Course Code: BCA-401
        Course Title: Database Systems
        Credits: 4
        Max Marks: 100

        Course Objectives:
        1. To introduce students to the fundamental concepts of database systems.
        2. To develop an understanding of relational algebra and SQL.
        3. Students will be able to design normalized schemas.

        Course Contents:
        Unit 1: Introduction to Databases
        - Data, information, DBMS
        - Relational model

        UNIT-II: SQL and Query Processing
        1. Basic SQL queries
        2. Joins, subqueries and views

        Module III - Normalization, Transactions and Indexing
        Unit IV
        Concurrency control and recovery

        Text Books:
        1. Elmasri &amp; Navathe, Fundamentals of Database Systems
        2. Silberschatz, Database System Concepts

        Reference Books:
        - Date, C. J., An Introduction to Database Systems
        Page 4 of 9
        """
        topics, stats = _extract_topics_with_stats(text)
        self.assertGreater(stats["noise_lines"], 8)
        self.assertEqual(stats["topics"], len(topics))
        for expected in [
            "Introduction to Databases",
            "Relational model",
            "SQL and Query Processing",
            "Basic SQL queries",
            "Normalization",
            "Concurrency control and recovery",
        ]:
            self.assertIn(expected, topics)
        joined = " | ".join(topics).lower()
        for banned in [
            "elmasri", "silberschatz", "max marks", "course objectives",
            "page 4", "credits", "department of computer science", "semester iv",
        ]:
            self.assertNotIn(banned, joined)
        self.assertNotIn("Unit IV", topics)

    def test_syllabus_preview_shows_clean_topics_and_edit_controls(self):
        self._register_and_login()
        response = self.client.post(
            "/roadmap/new",
            data={
                "title": "Database Systems",
                "roadmap_type": "syllabus",
                "source_text": (
                    "Course Objectives:\nStudents will understand databases.\n"
                    "Credits: 4\nCourse Contents:\n"
                    "Unit 1: Relational model\nUnit 2: SQL and Query Processing\n"
                    "Text Books:\n1. Elmasri, Fundamentals of Database Systems"
                ),
                "timeline_weeks": "4",
                "hours_per_week": "6",
                "study_days_per_week": "5",
                "pace_mode": "steady",
            },
            follow_redirects=False,
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Review Your Topics", body)
        self.assertIn("skipped", body)
        self.assertIn("Relational model", body)
        self.assertIn("data-topic-select-all", body)
        self.assertIn("data-topic-remove-selected", body)
        self.assertIn("data-topic-output", body)

    def test_editing_topics_rebuilds_unfinished_tasks_and_keeps_completed(self):
        self._register_and_login()
        response = self._create_roadmap(
            confirmed_topics="Algebra\nCalculus\nGeometry",
            plan_days="20",
            hours_per_day="1",
            study_days_per_week="5",
            start_date=datetime.now(UTC).date().isoformat(),
        )
        self.assertEqual(response.status_code, 302)
        roadmap_id = int(response.headers["Location"].rsplit("/", 1)[-1])

        edit_page = self.client.get(f"/roadmap/{roadmap_id}/topics")
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn("Save topics", edit_page.get_data(as_text=True))

        with app.app_context():
            first = Task.query.filter_by(roadmap_id=roadmap_id).order_by(Task.order_index.asc()).first()
            done_id = first.id
        update = self.client.post(
            f"/roadmap/{roadmap_id}/task/{done_id}/status",
            data={"status": "done", "completion_type": "planned"},
            follow_redirects=True,
        )
        self.assertEqual(update.status_code, 200)

        save = self.client.post(
            f"/roadmap/{roadmap_id}/topics",
            data={"confirmed_topics": "Algebra\nStatistics\nProbability"},
            follow_redirects=True,
        )
        self.assertEqual(save.status_code, 200)
        body = save.get_data(as_text=True)
        self.assertIn("Topics updated", body)
        self.assertIn("completed tasks were preserved", body.lower())

        with app.app_context():
            tasks = Task.query.filter_by(roadmap_id=roadmap_id).order_by(Task.order_index.asc()).all()
            titles = [task.title for task in tasks]
            roadmap = db.session.get(Roadmap, roadmap_id)
            self.assertIn(done_id, [task.id for task in tasks])
            self.assertEqual(db.session.get(Task, done_id).status, "done")
            self.assertTrue(any("Statistics" in title for title in titles))
            self.assertTrue(any("Probability" in title for title in titles))
            self.assertFalse(any("Geometry" in title for title in titles))
            self.assertFalse(any("Calculus" in title for title in titles))
            self.assertEqual(roadmap.total_tasks, len(tasks))
            self.assertEqual(roadmap.completed_tasks, 1)
            self.assertIn("Plan Topics:", roadmap.source_text)
            self.assertIn("Statistics", roadmap.source_text)

    def test_natural_language_plan_extracts_schedule_and_topics(self):
        plan = parse_plan_text(
            "I want to become a data analyst in 3 months, studying 2 hours a day, "
            "5 days a week. Topics: Excel, SQL, Power BI, statistics."
        )
        self.assertTrue(plan["understood"])
        self.assertEqual(plan["roadmap_type"], "career")
        self.assertEqual(plan["title"], "Data Analyst")
        self.assertEqual(plan["plan_days"], 90)
        self.assertAlmostEqual(plan["hours_per_day"], 2.0)
        self.assertEqual(plan["study_days_per_week"], 5)
        self.assertEqual(plan["topics"], ["Excel", "SQL", "Power BI", "statistics"])

        syllabus = parse_plan_text(
            "BCA semester 4 exam in 30 days, 3 hours daily. "
            "Subjects: DBMS, Operating Systems, Python, Computer Networks."
        )
        self.assertEqual(syllabus["roadmap_type"], "syllabus")
        self.assertEqual(syllabus["title"], "BCA Semester 4 Exam")
        self.assertEqual(syllabus["plan_days"], 30)
        self.assertEqual(syllabus["hours_per_day"], 3.0)
        self.assertEqual(
            syllabus["topics"],
            ["DBMS", "Operating Systems", "Python", "Computer Networks"],
        )

        empty = parse_plan_text("Hello there")
        self.assertFalse(empty["understood"])
        self.assertEqual(empty["title"], "")

    def test_natural_language_preview_endpoint_returns_form_values(self):
        self._register_and_login()
        response = self.client.post(
            "/roadmap/parse-nl",
            data={
                "nl_input": (
                    "Frontend developer career in 8 weeks, 90 minutes a day, beginner. "
                    "Topics: HTML, CSS, JavaScript, React."
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["understood"])
        self.assertEqual(payload["roadmap_type"], "career")
        self.assertEqual(payload["title"], "Frontend Developer")
        self.assertEqual(payload["plan_days"], 56)
        self.assertAlmostEqual(payload["hours_per_day"], 1.5)
        self.assertEqual(payload["current_level"], "beginner")
        self.assertEqual(payload["topics"], ["HTML", "CSS", "JavaScript", "React"])
        self.assertIn("56 days", payload["summary"])

    def test_natural_language_only_submission_creates_a_roadmap(self):
        self._register_and_login()
        response = self.client.post(
            "/roadmap/new",
            data={
                "nl_input": (
                    "I want to become a data analyst in 3 months, 2 hours a day, "
                    "5 days a week. Topics: Excel, SQL, Power BI, statistics."
                ),
                "title": "",
                "roadmap_type": "syllabus",
                "source_text": "",
                "plan_days": "0",
                "hours_per_day": "2",
                "study_days_per_week": "5",
                "pace_mode": "steady",
                "current_level": "beginner",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with app.app_context():
            roadmap = Roadmap.query.one()
            self.assertEqual(roadmap.roadmap_type, "career")
            self.assertEqual(roadmap.title, "Data Analyst")
            self.assertEqual(roadmap.plan_days, 90)
            self.assertAlmostEqual(roadmap.hours_per_day, 2.0)
            self.assertEqual(roadmap.hours_per_week, 10)
            titles = [task.title for task in Task.query.filter_by(roadmap_id=roadmap.id).all()]
            self.assertTrue(any("Excel" in title for title in titles))
            self.assertTrue(any("SQL" in title for title in titles))
            self.assertIn("Career Family", roadmap.source_text)

    def test_syllabus_natural_language_goes_through_topic_review(self):
        self._register_and_login()
        response = self.client.post(
            "/roadmap/new",
            data={
                "nl_input": (
                    "BCA semester 4 exam in 30 days, 3 hours daily. "
                    "Subjects: DBMS, Operating Systems, Python, Computer Networks."
                ),
                "title": "",
                "roadmap_type": "syllabus",
                "source_text": "",
                "plan_days": "0",
                "hours_per_day": "2",
                "study_days_per_week": "5",
                "pace_mode": "steady",
                "current_level": "beginner",
            },
            follow_redirects=False,
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Review Your Topics", body)
        self.assertIn("Understood from your sentence", body)
        self.assertIn("BCA Semester 4 Exam", body)
        self.assertIn("Operating Systems", body)
        self.assertIn("30 days", body)

    def test_upsc_pyq_quiz_scores_on_the_server(self):
        self._register_and_login()
        roadmap_id = self._create_upsc_roadmap()

        with patch("dashboard.routes.ensure_pyq_synced", return_value=FAKE_STATS), \
             patch("dashboard.routes.prelims_questions", side_effect=fake_prelims_questions):
            page = self.client.get(
                f"/roadmap/{roadmap_id}/quiz?mode=pyq&amount=5", follow_redirects=True
            )
            body = page.get_data(as_text=True)
            self.assertEqual(page.status_code, 200)
            qids = re.findall(r'name="qid_(\d+)" value="(\d+)"', body)
            self.assertEqual(len(qids), 5)

            answers = {"mode": "pyq"}
            for index, (_, qid) in enumerate(qids):
                answers[f"qid_{index}"] = qid
                answers[f"q_{index}"] = "b" if index == 4 else "a"
            submit = self.client.post(
                f"/roadmap/{roadmap_id}/quiz/submit",
                data=answers,
                follow_redirects=True,
            )

        result_body = submit.get_data(as_text=True)
        self.assertEqual(submit.status_code, 200)
        self.assertIn("Answer Review", result_body)
        self.assertIn("UPSC marking applied", result_body)
        with app.app_context():
            result = QuizResult.query.one()
            self.assertEqual(result.total_questions, 5)
            self.assertEqual(result.correct, 4)
            self.assertEqual(result.incorrect, 1)
            self.assertEqual(result.score, 7.33)
            self.assertEqual(result.mode, "pyq")

    def test_quiz_ignores_questions_from_another_roadmap(self):
        self._register_and_login()
        roadmap_id = self._create_upsc_roadmap()
        other = self._create_roadmap(title="Other Plan")
        other_id = int(other.headers["Location"].rsplit("/", 1)[-1])

        with app.app_context():
            user = User.query.filter_by(email="owner@example.com").one()
            foreign = QuizQuestion(
                question_text="Question owned by another roadmap",
                options_json='["A", "B", "C", "D"]',
                correct_answer="a",
                user_id=user.id,
                roadmap_id=other_id,
            )
            db.session.add(foreign)
            db.session.commit()
            foreign_id = foreign.id

        response = self.client.post(
            f"/roadmap/{roadmap_id}/quiz/submit",
            data={"qid_0": str(foreign_id), "q_0": "a"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("submission was empty", response.get_data(as_text=True))
        with app.app_context():
            self.assertEqual(QuizResult.query.count(), 0)

    def test_full_mock_builds_exactly_one_hundred_questions(self):
        self._register_and_login()
        roadmap_id = self._create_upsc_roadmap()

        with patch("dashboard.routes.ensure_pyq_synced", return_value=FAKE_STATS), \
             patch("dashboard.routes.prelims_questions", side_effect=fake_prelims_questions):
            page = self.client.get(
                f"/roadmap/{roadmap_id}/quiz?mode=mock", follow_redirects=True
            )
            body = page.get_data(as_text=True)
            self.assertEqual(page.status_code, 200)
            qids = re.findall(r'name="qid_(\d+)" value="(\d+)"', body)
            self.assertEqual(len(qids), 100)

            payload = {"mode": "mock"}
            for index, (_, qid) in enumerate(qids):
                payload[f"qid_{index}"] = qid
                payload[f"q_{index}"] = "a"
            submit = self.client.post(
                f"/roadmap/{roadmap_id}/quiz/submit", data=payload, follow_redirects=True
            )

        self.assertEqual(submit.status_code, 200)
        with app.app_context():
            result = QuizResult.query.one()
            self.assertEqual(result.total_questions, 100)
            self.assertEqual(result.correct, 100)
            self.assertEqual(result.score, 200.0)
            self.assertEqual(result.mode, "mock")

    def test_mains_interview_and_materials_pages_render(self):
        self._register_and_login()
        roadmap_id = self._create_upsc_roadmap()
        with app.app_context():
            db.session.add_all(
                [
                    Question(
                        exam="UPSC",
                        subject="Polity",
                        topic="GS-II",
                        question_text="Discuss the role of the Finance Commission in fiscal federalism.",
                        answer_text="Rule-based framework: define, analyse, conclude.",
                        difficulty="medium",
                        stage="mains",
                        year=2019,
                        paper="GS-II",
                        source_name="UPSC CSE Mains",
                        is_public=True,
                    ),
                    Question(
                        exam="UPSC",
                        subject="Economy",
                        topic="GS-III",
                        question_text="Examine the impact of digital public infrastructure on financial inclusion.",
                        answer_text="Rule-based framework: define, analyse, conclude.",
                        difficulty="hard",
                        stage="mains",
                        year=2021,
                        paper="GS-III",
                        source_name="UPSC CSE Mains",
                        is_public=True,
                    ),
                ]
            )
            db.session.commit()

        mains = self.client.get(f"/roadmap/{roadmap_id}/mains", follow_redirects=True)
        mains_body = mains.get_data(as_text=True)
        self.assertEqual(mains.status_code, 200)
        self.assertIn("Mains PYQ Practice", mains_body)
        self.assertIn("Show answer framework", mains_body)

        interview = self.client.get(f"/roadmap/{roadmap_id}/interview", follow_redirects=True)
        interview_body = interview.get_data(as_text=True)
        self.assertEqual(interview.status_code, 200)
        self.assertIn("Interview Practice", interview_body)
        self.assertIn("Start 2-min timer", interview_body)

        materials = self.client.get(f"/roadmap/{roadmap_id}/materials", follow_redirects=True)
        materials_body = materials.get_data(as_text=True)
        self.assertEqual(materials.status_code, 200)
        self.assertIn("Free UPSC Materials Hub", materials_body)
        self.assertIn("UPSC previous year papers", materials_body)

    def test_upload_is_limited_to_its_owner(self):
        os.makedirs(self.upload_dir, exist_ok=True)
        with open(os.path.join(self.upload_dir, "proof.txt"), "w", encoding="utf-8") as handle:
            handle.write("evidence")

        self._register_and_login()
        with app.app_context():
            user = User.query.filter_by(email="owner@example.com").one()
            roadmap = Roadmap(
                title="Owned plan",
                roadmap_type="syllabus",
                start_date=date(2026, 11, 2),
                target_date=date(2026, 12, 1),
                user_id=user.id,
            )
            db.session.add(roadmap)
            db.session.flush()
            db.session.add(
                Task(
                    title="Owned task",
                    roadmap_id=roadmap.id,
                    evidence_path="proof.txt",
                )
            )
            db.session.commit()

        owner_view = self.client.get("/uploads/proof.txt")
        self.assertEqual(owner_view.status_code, 200)
        self.assertEqual(owner_view.data, b"evidence")

        self.client.post("/logout", follow_redirects=True)
        self._register_and_login(email="other@example.com")
        blocked = self.client.get("/uploads/proof.txt", follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        self.assertNotEqual(blocked.data, b"evidence")

    def test_pyq_validator_rejects_noise(self):
        flagged = set()
        seen = set()
        base = {
            "year": 2020,
            "q_num": 1,
            "question": "Consider the following statements about the Indian Constitution and choose the correct answer.",
            "option_a": "(a) One",
            "option_b": "(b) Two",
            "option_c": "(c) Three",
            "option_d": "(d) Four",
            "correct_option": "b",
            "topic": "Polity",
            "subtopic": "Constitution",
            "difficulty": "medium",
        }
        record, reason = _validate_prelims_item(base, flagged, seen)
        self.assertIsNotNone(record, reason)
        self.assertEqual(record["correct_answer"], "b")
        self.assertEqual(record["stage"], "prelims")

        unverified = dict(base, year=2016)
        archive_record, reason = _validate_prelims_item(unverified, set(), set())
        self.assertIsNotNone(archive_record, reason)
        self.assertEqual(archive_record["verification"], "archive")
        self.assertEqual(archive_record["quality_score"], 0.8)
        self.assertIn("not officially verified", archive_record["source_name"])

        rejected_year = dict(base, year=2012)
        self.assertIsNone(_validate_prelims_item(rejected_year, set(), set())[0])

        merged = dict(base, question="Choose the correct answer. (a) One (b) Two (c) Three (d) Four")
        self.assertIsNone(_validate_prelims_item(merged, set(), set())[0])

        duplicate = dict(base, option_b="(b) One")
        self.assertIsNone(_validate_prelims_item(duplicate, set(), set())[0])

        duplicate_key = dict(base, q_num=2)
        self.assertIsNone(_validate_prelims_item(duplicate_key, set(), seen)[0])

    def test_seed_fixture_is_present_and_verified(self):
        with app.app_context():
            self.assertTrue(seed_available())
            path = app.config["PYQ_SEED_PATH"]
            records = _read_seed(path)
        self.assertGreaterEqual(len(records), 1000)
        self.assertTrue(any(item.get("verification") == "verified" for item in records))
        self.assertTrue(all(item.get("external_id") for item in records))

    def test_conditional_fetch_uses_etag_and_handles_304(self):
        state = PyqSyncState(
            source="prelims",
            etag='"v1"',
            last_modified="Tue, 01 Jan 2025 00:00:00 GMT",
        )

        class NotModified:
            status_code = 304
            content = b""
            headers = {}

        with patch("pyq.bank.requests.get", return_value=NotModified()) as request:
            payload, not_modified = _http_get_json("https://example.test/data.json", state=state)
        self.assertTrue(not_modified)
        self.assertIsNone(payload)
        sent = request.call_args.kwargs["headers"]
        self.assertEqual(sent["If-None-Match"], '"v1"')
        self.assertEqual(sent["If-Modified-Since"], "Tue, 01 Jan 2025 00:00:00 GMT")
        self.assertEqual(state.etag, '"v1"')

        class Fresh:
            status_code = 200
            content = b'[{"year": 2020}]'
            headers = {"ETag": '"v2"', "Last-Modified": "Wed, 02 Jan 2025 00:00:00 GMT"}

            def raise_for_status(self):
                return None

            def json(self):
                return [{"year": 2020}]

        with patch("pyq.bank.requests.get", return_value=Fresh()):
            payload, not_modified = _http_get_json("https://example.test/data.json", state=state)
        self.assertFalse(not_modified)
        self.assertEqual(payload, [{"year": 2020}])
        self.assertEqual(state.etag, '"v2"')
        self.assertEqual(len(state.content_hash), 64)

    def test_taxonomy_filters_figure_questions_and_tags_topics(self):
        self.assertFalse(
            is_self_contained(
                "With reference to the map given below, identify the states through which the river flows."
            )
        )
        self.assertFalse(is_self_contained("The figure given below shows the pressure belts. Identify them."))
        self.assertTrue(
            is_self_contained(
                "Consider the following statements about fundamental rights and choose the correct answer."
            )
        )
        subject, topic = classify_topic(
            "Consider the following statements about fundamental rights under the Constitution.",
            "Polity",
        )
        self.assertEqual(subject, "Polity")
        self.assertIn("Fundamental", topic)

    def test_official_prelims_parser_builds_verified_records(self):
        paper = """
        1. Consider the following statements about the Indian Constitution:
        1. It provides for a federal system.
        2. It provides for judicial review.
        Which of the statements given above is/are correct?
        (a) 1 only
        (b) 2 only
        (c) Both 1 and 2
        (d) Neither 1 nor 2
        2. With reference to the Indian economy, consider the following statements:
        1. Repo rate is the rate at which RBI lends to commercial banks.
        Which of the statements given above is/are correct?
        (a) 1 only (b) 2 only (c) Both 1 and 2 (d) Neither 1 nor 2
        """
        result = build_prelims_records(paper, 2024, key_text="1. (c)\n2. (a)\n")
        self.assertEqual(result["parsed_blocks"], 2)
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["missing_keys"], [])
        first = result["records"][0]
        self.assertEqual(first["correct_answer"], "c")
        self.assertEqual(first["verification"], "verified")
        self.assertEqual(first["external_id"], "official:prelims:2024:1")
        self.assertEqual(first["options_json"], '["1 only", "2 only", "Both 1 and 2", "Neither 1 nor 2"]')

        missing = build_prelims_records(paper, 2024, key_text="1. (c)\n")
        self.assertEqual(missing["missing_keys"], [2])
        self.assertEqual(len(missing["records"]), 1)

    def test_official_key_parser_handles_sets_and_conflicts(self):
        keys = "SET A\n1. (b)\n2. (c)\nSET B\n1. (d)\n2. (a)\n"
        self.assertEqual(parse_answer_key(keys, key_set="A"), {1: "b", 2: "c"})
        self.assertEqual(parse_answer_key(keys, key_set="B"), {1: "d", 2: "a"})
        with self.assertRaises(OfficialPaperError):
            parse_answer_key("1. (a)\n1. (b)\n")

    def test_official_mains_parser_strips_marks_and_builds_framework(self):
        paper = """
        SECTION A
        1. Explain the role of the Election Commission in ensuring free and fair elections in India. (10 marks, 150 words)
        2. Critically examine the impact of climate change on Indian agriculture. (15 marks, 250 words)
        """
        result = build_mains_records(paper, 2024, "GS-II")
        self.assertEqual(len(result["records"]), 2)
        first, second = result["records"]
        self.assertNotIn("10 marks", first["question_text"])
        self.assertEqual(first["difficulty"], "medium")
        self.assertEqual(second["difficulty"], "hard")
        self.assertEqual(second["verification"], "imported")
        self.assertEqual(second["paper"], "GS-II")
        self.assertIn("Answer framework", second["answer_text"])

    def test_scanned_pdf_reports_missing_text_layer(self):
        from PyPDF2 import PdfWriter

        path = os.path.join(self.upload_dir, "blank.pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with open(path, "wb") as handle:
            writer.write(handle)
        with self.assertRaises(OfficialPaperError) as caught:
            extract_pdf_text(path)
        self.assertEqual(caught.exception.code, "no_text_layer")

    def _question(self, external_id, text, subject, topic, year=2020, verification="verified"):
        return Question(
            exam="UPSC",
            subject=subject,
            topic=topic,
            question_text=text,
            difficulty="medium",
            is_public=True,
            stage="prelims",
            year=year,
            paper="GS Paper I",
            options_json='["One", "Two", "Three", "Four"]',
            correct_answer="a",
            source_name="test",
            source_url="https://example.test",
            external_id=external_id,
            quality_score=1.0,
            verification=verification,
        )

    def test_weak_topic_selection_prefers_exact_topic(self):
        with app.app_context():
            db.session.add_all([
                self._question(
                    "t:1",
                    "Which one of the following statements about the Indian judiciary is correct?",
                    "Polity",
                    "Judiciary",
                ),
                self._question(
                    "t:2",
                    "Consider the following statements about the Constitution and choose the correct answer.",
                    "Polity",
                    "Constitutional Framework",
                ),
                self._question(
                    "t:3",
                    "Which of the following statements about Parliament is correct?",
                    "Polity",
                    "Parliament and Legislature",
                ),
                self._question(
                    "t:4",
                    "Which of the following statements about the Harappan civilisation is correct?",
                    "History",
                    "Ancient India",
                ),
                self._question(
                    "t:5",
                    "Which of the following statements about the monsoon is correct?",
                    "Geography",
                    "Physical Geography",
                    verification="archive",
                ),
            ])
            db.session.commit()

            picked = prelims_questions(amount=1, topics=["Judiciary"])
            self.assertEqual(len(picked), 1)
            self.assertEqual(picked[0]["topic"], "Judiciary")

            archive_only = prelims_questions(amount=5, archive_only=True)
            self.assertEqual(len(archive_only), 1)
            self.assertEqual(archive_only[0]["topic"], "Physical Geography")

    def test_coverage_stats_counts_verification_tiers(self):
        with app.app_context():
            db.session.add_all([
                self._question(
                    "c:1",
                    "Which of the following statements about the Constitution is correct?",
                    "Polity",
                    "Constitutional Framework",
                    year=2020,
                    verification="verified",
                ),
                self._question(
                    "c:2",
                    "Which of the following statements about the judiciary is correct?",
                    "Polity",
                    "Judiciary",
                    year=2021,
                    verification="verified",
                ),
                self._question(
                    "c:3",
                    "Which of the following statements about the monsoon is correct?",
                    "Geography",
                    "Physical Geography",
                    year=2024,
                    verification="archive",
                ),
            ])
            db.session.add(
                Question(
                    exam="UPSC",
                    subject="Polity",
                    topic="Governance and Civil Services",
                    question_text="Discuss the role of civil services in a welfare state.",
                    difficulty="medium",
                    is_public=True,
                    stage="mains",
                    year=2023,
                    paper="GS-II",
                    source_name="test",
                    source_url="https://example.test",
                    external_id="c:mains:1",
                    quality_score=1.0,
                    verification="imported",
                )
            )
            db.session.commit()
            stats = coverage_stats()
        self.assertEqual(stats["prelims_total"], 3)
        self.assertEqual(stats["mains_total"], 1)
        self.assertEqual(stats["verified_total"], 2)
        self.assertEqual(stats["archive_total"], 2)
        self.assertEqual(stats["by_year"], {2020: 1, 2021: 1, 2024: 1})
        self.assertEqual(stats["verification"]["prelims"]["archive"], 1)
        self.assertEqual(stats["verification"]["mains"]["imported"], 1)


if __name__ == "__main__":
    unittest.main()
