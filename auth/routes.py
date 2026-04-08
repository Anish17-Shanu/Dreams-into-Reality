from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from models.models import User
from extensions import db
import re

auth_bp = Blueprint('auth', __name__)


def _valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def _password_feedback(password):
    if len(password) < 8:
        return "Use at least 8 characters for your password."
    if password.lower() == password or password.upper() == password:
        return "Use a mix of uppercase and lowercase letters."
    if not any(ch.isdigit() for ch in password):
        return "Add at least one number to your password."
    return None

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        if not _valid_email(email):
            flash('Enter a valid email address.')
            return redirect(url_for('auth.register'))

        password_issue = _password_feedback(password)
        if password_issue:
            flash(password_issue)
            return redirect(url_for('auth.register'))

        password_hash = generate_password_hash(password)

        if User.query.filter_by(email=email).first():
            flash('Email already exists.')
            return redirect(url_for('auth.register'))

        user = User(email=email, password=password_hash)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful.')
        return redirect(url_for('auth.login'))

    return render_template('register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        if not _valid_email(email):
            flash('Enter a valid email address.')
            return render_template('login.html')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, request.form['password']):
            session.clear()
            session.permanent = True
            session['user_id'] = user.id
            return redirect(url_for('dashboard.dashboard'))
        flash('Invalid credentials.')
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('auth.login'))
