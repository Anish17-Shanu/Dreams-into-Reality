from extensions import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    roadmaps = db.relationship('Roadmap', backref='user', lazy=True, passive_deletes=True)


class Roadmap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    roadmap_type = db.Column(db.String(40), nullable=False)  # syllabus | career
    source_text = db.Column(db.Text, nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    target_date = db.Column(db.Date, nullable=False)
    total_tasks = db.Column(db.Integer, default=0)
    completed_tasks = db.Column(db.Integer, default=0)
    total_hours_est = db.Column(db.Float, default=0.0)
    hours_per_week = db.Column(db.Integer, default=6)
    study_days_per_week = db.Column(db.Integer, default=5)
    timezone = db.Column(db.String(60), default="Asia/Kolkata")
    streak = db.Column(db.Integer, default=0)
    last_checkin_date = db.Column(db.Date, nullable=True)
    resource_fetch_status = db.Column(db.String(20), default="idle")  # idle | running | done | failed
    resource_fetch_started_at = db.Column(db.DateTime, nullable=True)
    resource_fetch_completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tasks = db.relationship('Task', backref='roadmap', lazy=True, cascade="all, delete-orphan", passive_deletes=True)
    checkins = db.relationship('Checkin', backref='roadmap', lazy=True, cascade="all, delete-orphan", passive_deletes=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(220), nullable=False)
    order_index = db.Column(db.Integer, default=0)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="todo")  # todo | doing | done
    difficulty = db.Column(db.String(20), default="medium")  # easy | medium | hard
    estimated_hours = db.Column(db.Float, default=1.5)
    actual_hours = db.Column(db.Float, default=0.0)
    completion_type = db.Column(db.String(20), default="planned")  # planned | alternative
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    evidence_path = db.Column(db.String(400), nullable=True)
    last_resource_refresh = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id'), nullable=False)
    resources = db.relationship('Resource', backref='task', lazy=True, cascade="all, delete-orphan", passive_deletes=True)


class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(40), nullable=False)  # wikipedia | github | crossref | openalex
    title = db.Column(db.String(220), nullable=False)
    url = db.Column(db.String(600), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    score = db.Column(db.Float, default=0.0)
    rating_avg = db.Column(db.Float, default=0.0)
    rating_count = db.Column(db.Integer, default=0)
    flagged_count = db.Column(db.Integer, default=0)
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False)
    feedback = db.relationship('ResourceFeedback', backref='resource', lazy=True, cascade="all, delete-orphan", passive_deletes=True)


class ResourceFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=True)  # 1-5
    flagged = db.Column(db.Boolean, default=False)
    comment = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resource_id = db.Column(db.Integer, db.ForeignKey('resource.id'), nullable=False)


class Checkin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    checkin_date = db.Column(db.Date, nullable=False)
    minutes = db.Column(db.Integer, default=0)
    note = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id'), nullable=False)


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam = db.Column(db.String(80), nullable=False)  # e.g., UPSC
    subject = db.Column(db.String(120), nullable=True)
    topic = db.Column(db.String(160), nullable=True)
    question_text = db.Column(db.Text, nullable=False)
    answer_text = db.Column(db.Text, nullable=True)
    difficulty = db.Column(db.String(20), default="medium")
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuestionAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    score = db.Column(db.Integer, default=0)  # 0-5 self-score
    notes = db.Column(db.String(400), nullable=True)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)


class PyqCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam = db.Column(db.String(120), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id'), nullable=False)


class MockTestSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    scheduled_date = db.Column(db.Date, nullable=False)
    duration_minutes = db.Column(db.Integer, default=90)
    questions_count = db.Column(db.Integer, default=50)
    status = db.Column(db.String(20), default="planned")  # planned | completed | missed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id'), nullable=False)


class QuizResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total_questions = db.Column(db.Integer, default=0)
    correct = db.Column(db.Integer, default=0)
    incorrect = db.Column(db.Integer, default=0)
    score = db.Column(db.Float, default=0.0)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id'), nullable=False)
