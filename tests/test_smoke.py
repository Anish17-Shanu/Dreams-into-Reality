import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["AUTO_CREATE_SCHEMA"] = "false"

from app import app
from extensions import db
from models.models import User


class DreamsIntoRealitySmokeTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI=f"sqlite:///{self.db_path}",
            AUTO_CREATE_SCHEMA=False,
            ENABLE_EXTERNAL_RESOURCES=False,
            SESSION_COOKIE_SECURE=False,
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
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _register_and_login(self):
        self.client.post(
            "/register",
            data={"email": "owner@example.com", "password": "StrongPass1"},
            follow_redirects=True,
        )
        self.client.post(
            "/login",
            data={"email": "owner@example.com", "password": "StrongPass1"},
            follow_redirects=True,
        )

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

    def test_syllabus_creation_and_view_flow(self):
        self._register_and_login()
        response = self.client.post(
            "/roadmap/new",
            data={
                "title": "Math Sprint",
                "roadmap_type": "syllabus",
                "source_text": "Unit 1: Algebra\nUnit 2: Calculus",
                "confirmed_topics": "Algebra\nCalculus",
                "timeline_weeks": "4",
                "hours_per_week": "6",
                "study_days_per_week": "5",
                "pace_mode": "steady",
            },
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Math Sprint", body)
        self.assertIn("Tasks", body)
        self.assertIn("Recovery Options", body)
        self.assertIn("Risk Radar", body)
        self.assertIn("Plan Quality Control", body)
        self.assertIn("Focus Session", body)
        self.assertIn("Monthly review", body)
        self.assertIn("Revision Engine", body)
        self.assertIn("Analytics", body)
        self.assertIn("Accountability Loop", body)

    def test_view_roadmap_degrades_if_optional_tables_are_missing(self):
        self._register_and_login()
        create_response = self.client.post(
            "/roadmap/new",
            data={
                "title": "Career Clarity",
                "roadmap_type": "career",
                "timeline_weeks": "6",
                "hours_per_week": "6",
                "study_days_per_week": "5",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with patch("dashboard.routes._has_table", side_effect=lambda name: name not in {"mock_test_schedule", "quiz_result", "question_attempt", "pyq_completion"}):
            response = self.client.get(create_response.headers["Location"], follow_redirects=True)

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Career Clarity", body)

    def test_upsc_practice_and_quiz_result_surfaces_render(self):
        self._register_and_login()
        create_response = self.client.post(
            "/upsc/new",
            data={
                "title": "UPSC System",
                "upsc_focus": "full_journey",
                "timeline_weeks": "8",
                "hours_per_week": "10",
                "study_days_per_week": "6",
                "pace_mode": "steady",
                "confirmed_topics": "UPSC exam strategy and attempt planning\nNCERT foundation build-up",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        roadmap_path = create_response.headers["Location"]
        roadmap_id = roadmap_path.rsplit("/", 1)[-1]

        practice_response = self.client.get(f"/roadmap/{roadmap_id}/practice", follow_redirects=True)
        practice_body = practice_response.get_data(as_text=True)
        self.assertEqual(practice_response.status_code, 200)
        self.assertIn("Weak-Area Radar", practice_body)
        self.assertIn("Practice Coach", practice_body)
        self.assertIn("Gap signal", practice_body)

        quiz_submit = self.client.post(
            f"/roadmap/{roadmap_id}/quiz/submit",
            data={"total": "2", "q_0": "A", "a_0": "A", "q_1": "B", "a_1": "C"},
            follow_redirects=True,
        )
        quiz_body = quiz_submit.get_data(as_text=True)
        self.assertEqual(quiz_submit.status_code, 200)
        self.assertIn("Quiz Analysis", quiz_body)
        self.assertIn("Best next step", quiz_body)

        weekly_quiz = self.client.get(
            f"/roadmap/{roadmap_id}/quiz?mode=weekly&amount=5&difficulty=medium",
            follow_redirects=True,
        )
        weekly_body = weekly_quiz.get_data(as_text=True)
        self.assertEqual(weekly_quiz.status_code, 200)
        self.assertIn("Weekly assessment focus", weekly_body)
        self.assertIn("Source:", weekly_body)
        self.assertIn("name=\"qid_0\"", weekly_body)

    def test_demo_and_text_exports_render(self):
        self._register_and_login()
        create_response = self.client.post(
            "/roadmap/new",
            data={
                "title": "Career Clarity",
                "roadmap_type": "career",
                "timeline_weeks": "6",
                "hours_per_week": "6",
                "study_days_per_week": "5",
                "workflow_mode": "deadline",
                "target_outcome": "portfolio-ready",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        roadmap_id = create_response.headers["Location"].rsplit("/", 1)[-1]

        demo_response = self.client.get("/demo")
        self.assertEqual(demo_response.status_code, 200)
        self.assertIn("Demo roadmap", demo_response.get_data(as_text=True))

        monthly_export = self.client.get(f"/roadmap/{roadmap_id}/export/monthly-review.txt")
        self.assertEqual(monthly_export.status_code, 200)
        self.assertIn("Monthly Review", monthly_export.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
