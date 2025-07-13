from flask import Blueprint, render_template, request, redirect, session, url_for
from extensions import db
from models.models import User, Subject
from datetime import datetime
from datetime import timedelta
dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
def home():
    return redirect(url_for('auth.login'))

@dashboard_bp.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    user = User.query.get(session['user_id'])
    subjects = Subject.query.filter_by(user_id=user.id).all()
    total = sum(s.total_topics for s in subjects)
    done = sum(s.completed_topics for s in subjects)
    overall_progress = round((done / total) * 100, 2) if total > 0 else 0

# after subjects = ...
    analytics_data = []
    for s in subjects:
        days_spent = max((datetime.utcnow() - s.created_at).days, 1)
        pace = s.completed_topics / days_spent
        est_days_left = (s.total_topics - s.completed_topics) / pace if pace > 0 else None
        est_finish_date = datetime.utcnow() + timedelta(days=est_days_left) if est_days_left else None
        overdue = s.deadline and est_finish_date and est_finish_date.date() > s.deadline

        analytics_data.append({
            'id': s.id,
            'name': s.name,
            'completed': s.completed_topics,
            'remaining': s.total_topics - s.completed_topics,
            'est_finish_date': est_finish_date.strftime("%Y-%m-%d") if est_finish_date else "Unknown",
            'deadline': s.deadline,
            'overdue': overdue
        })

    return render_template('dashboard.html', user=user, subjects=subjects,
                       overall_progress=overall_progress,
                       analytics_data=analytics_data)



@dashboard_bp.route('/add', methods=['GET', 'POST'])
def add_subject():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        name = request.form['name']
        total = int(request.form['total_topics'])
        deadline = request.form.get('deadline')
        deadline_date = datetime.strptime(deadline, "%Y-%m-%d").date() if deadline else None

        subject = Subject(name=name, total_topics=total, completed_topics=0, user_id=session['user_id'], deadline=deadline_date)
        db.session.add(subject)
        db.session.commit()
        return redirect(url_for('dashboard.dashboard'))

    return render_template('add_subject.html')

@dashboard_bp.route('/edit/<int:subject_id>', methods=['GET', 'POST'])
def edit_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)

    if request.method == 'POST':
        subject.name = request.form['name']
        subject.total_topics = int(request.form['total_topics'])
        subject.deadline = datetime.strptime(request.form['deadline'], "%Y-%m-%d").date() if request.form['deadline'] else None
        db.session.commit()
        return redirect(url_for('dashboard.dashboard'))

    return render_template('edit_subject.html', subject=subject)

@dashboard_bp.route('/update/<int:subject_id>', methods=['POST'])
def update_progress(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    subject.completed_topics = int(request.form['completed'])
    db.session.commit()
    return redirect(url_for('dashboard.dashboard'))

@dashboard_bp.route('/delete/<int:subject_id>', methods=['POST'])
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    return redirect(url_for('dashboard.dashboard'))

