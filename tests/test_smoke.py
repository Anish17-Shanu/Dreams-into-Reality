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
            },
            follow_redirects=True,
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Math Sprint", body)
        self.assertIn("Tasks", body)

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


if __name__ == "__main__":
    unittest.main()
