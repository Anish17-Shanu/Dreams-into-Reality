from extensions import db
from datetime import datetime

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)
    roadmaps = db.relationship('Roadmap', backref='user', lazy=True)


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
    timezone = db.Column(db.String(60), default="UTC")
    streak = db.Column(db.Integer, default=0)
    last_checkin_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tasks = db.relationship('Task', backref='roadmap', lazy=True, cascade="all, delete-orphan")
    checkins = db.relationship('Checkin', backref='roadmap', lazy=True, cascade="all, delete-orphan")


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
    resources = db.relationship('Resource', backref='task', lazy=True, cascade="all, delete-orphan")


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
    feedback = db.relationship('ResourceFeedback', backref='resource', lazy=True, cascade="all, delete-orphan")


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
