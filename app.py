from flask import Flask, render_template, redirect, url_for, request, flash, session
from models import User, Subject
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "track_secret"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
db.init_app(app)

with app.app_context():
    db.create_all()

from models import User, Subject
with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(email=email).first():
            flash("User already exists")
            return redirect(url_for('register'))
        user = User(email=email, password=password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        else:
            flash("Login Failed")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])
    subjects = Subject.query.filter_by(user_id=user.id).all()

    total_topics = sum(subject.total_topics for subject in subjects)
    completed_topics = sum(subject.completed_topics for subject in subjects)

    overall_progress = 0
    if total_topics > 0:
        overall_progress = round((completed_topics / total_topics) * 100, 2)

    # ✅ Pass `overall_progress` into the template:
    return render_template(
        'dashboard.html',
        subjects=subjects,
        overall_progress=overall_progress
    )


@app.route('/add_subject', methods=['GET', 'POST'])
def add_subject():
    if request.method == 'POST':
        name = request.form['name']
        total = int(request.form['total'])
        subject = Subject(name=name, total_topics=total, completed_topics=0, user_id=session['user_id'])
        db.session.add(subject)
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template('add_subject.html')

@app.route('/update_progress/<int:subject_id>', methods=['POST'])
def update_progress(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    if subject.user_id != session['user_id']:
        return "Unauthorized", 403
    subject.completed_topics = int(request.form['completed'])
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/delete_subject/<int:subject_id>', methods=['POST'])
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    if subject.user_id != session['user_id']:
        return "Unauthorized", 403
    db.session.delete(subject)
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render sets $PORT
    app.run(host="0.0.0.0", port=port, debug=True)
