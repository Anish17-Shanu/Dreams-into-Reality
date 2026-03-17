from flask import Blueprint, render_template, request, redirect, session, url_for, current_app, flash
from extensions import db
from models.models import User, Roadmap, Task, Resource
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import re
import requests
from urllib.parse import quote

dashboard_bp = Blueprint('dashboard', __name__)

CAREER_TEMPLATES = {
    "frontend developer": {
        "topics": [
            "HTML fundamentals", "CSS layout and responsive design", "JavaScript fundamentals",
            "TypeScript basics", "React core concepts", "State management", "API integration",
            "Testing and debugging", "Accessibility", "Performance optimization", "Deployment"
        ],
        "projects": [
            "Portfolio website", "Responsive landing page", "React dashboard", "API-driven app",
            "Accessible UI redesign"
        ],
    },
    "data analyst": {
        "topics": [
            "Spreadsheet mastery", "SQL fundamentals", "Data cleaning", "Exploratory data analysis",
            "Visualization principles", "Statistics basics", "Python for analytics", "Dashboards",
            "Storytelling with data", "Business metrics"
        ],
        "projects": [
            "KPI dashboard", "Customer churn analysis", "Sales forecasting report"
        ],
    },
    "data scientist": {
        "topics": [
            "Python fundamentals", "Linear algebra and calculus basics", "Probability and statistics",
            "Feature engineering", "Supervised learning", "Unsupervised learning", "Model evaluation",
            "Deep learning basics", "MLOps foundations", "Ethics in AI"
        ],
        "projects": [
            "Predictive model", "Clustering analysis", "NLP mini project"
        ],
    },
    "cybersecurity": {
        "topics": [
            "Networking fundamentals", "Linux basics", "Threat modeling", "Web security",
            "Vulnerability assessment", "Incident response", "SIEM basics", "Cloud security",
            "Security automation", "Compliance and governance"
        ],
        "projects": [
            "Home lab security audit", "Threat model for a web app", "Incident response playbook"
        ],
    },
    "ai engineer": {
        "topics": [
            "Python foundations", "Data pipelines", "ML fundamentals", "Model deployment",
            "LLM basics", "Prompting patterns", "Evaluation & monitoring", "Vector search",
            "API integration", "Ethics and safety"
        ],
        "projects": [
            "RAG demo app", "Model monitoring dashboard", "LLM-powered workflow automation"
        ],
    },
}


def login_required(view_func):
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def _normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def _extract_topics_from_text(text):
    if not text:
        return []
    lines = [l.strip(" -•\t") for l in text.splitlines()]
    lines = [l for l in lines if len(l) > 2]
    if len(lines) <= 2:
        parts = re.split(r"[.;]\s+", text)
        lines = [p.strip() for p in parts if len(p.strip()) > 2]
    unique = []
    for item in lines:
        if item.lower() not in [u.lower() for u in unique]:
            unique.append(item)
    return unique[:50]


def _extract_text_from_pdf(file_path):
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        text = []
        for page in reader.pages[:10]:
            text.append(page.extract_text() or "")
        return "\n".join(text).strip()
    except Exception:
        return ""


def _safe_get(url, headers=None, params=None, timeout=8):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


def _fetch_resources_for_topic(topic):
    if not current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
        return []

    resources = []
    user_agent = current_app.config.get("WIKIPEDIA_USER_AGENT")
    headers = {"User-Agent": user_agent}

    wiki_title = quote(topic.replace(" ", "_"))
    wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_title}"
    wiki_data = _safe_get(wiki_url, headers=headers)
    if wiki_data and wiki_data.get("content_urls"):
        resources.append({
            "provider": "wikipedia",
            "title": wiki_data.get("title", topic),
            "url": wiki_data["content_urls"]["desktop"]["page"],
            "summary": wiki_data.get("extract", "")
        })

    crossref_params = {
        "query.title": topic,
        "rows": 2,
    }
    if current_app.config.get("CROSSREF_MAILTO"):
        crossref_params["mailto"] = current_app.config["CROSSREF_MAILTO"]
    crossref_data = _safe_get("https://api.crossref.org/works", headers=headers, params=crossref_params)
    if crossref_data and crossref_data.get("message", {}).get("items"):
        for item in crossref_data["message"]["items"][:2]:
            title = (item.get("title") or [topic])[0]
            url = item.get("URL", "")
            if url:
                resources.append({
                    "provider": "crossref",
                    "title": title,
                    "url": url,
                    "summary": "Academic reference"
                })

    github_headers = {"Accept": "application/vnd.github+json", "User-Agent": user_agent}
    token = current_app.config.get("GITHUB_TOKEN")
    if token:
        github_headers["Authorization"] = f"Bearer {token}"
    github_params = {"q": topic, "sort": "stars", "order": "desc", "per_page": 2}
    github_data = _safe_get("https://api.github.com/search/repositories", headers=github_headers, params=github_params)
    if github_data and github_data.get("items"):
        for repo in github_data["items"][:2]:
            resources.append({
                "provider": "github",
                "title": repo.get("full_name", topic),
                "url": repo.get("html_url", ""),
                "summary": repo.get("description", "")
            })

    return resources


def _build_tasks(roadmap_type, topics, projects, start_date, weeks):
    tasks = []
    all_items = topics[:]
    if roadmap_type == "career":
        for project in projects:
            all_items.append(f"Project: {project}")
    if not all_items:
        all_items = ["Define milestones", "Gather resources", "Start learning", "Build a mini project"]

    total_days = max(weeks * 7, 7)
    interval = max(total_days // len(all_items), 1)
    for idx, item in enumerate(all_items):
        due_date = start_date + timedelta(days=idx * interval)
        tasks.append({
            "title": item,
            "order_index": idx + 1,
            "due_date": due_date
        })
    return tasks


@dashboard_bp.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard.dashboard'))
    return render_template('home.html')


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    roadmaps = Roadmap.query.filter_by(user_id=user.id).order_by(Roadmap.created_at.desc()).all()
    return render_template('dashboard.html', user=user, roadmaps=roadmaps)


@dashboard_bp.route('/roadmap/new', methods=['GET', 'POST'])
@login_required
def create_roadmap():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        roadmap_type = request.form.get('roadmap_type', 'syllabus')
        timeline_weeks = int(request.form.get('timeline_weeks', 8))
        timeline_weeks = max(2, min(52, timeline_weeks))
        start_date_str = request.form.get('start_date')
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else datetime.utcnow().date()

        raw_text = request.form.get('source_text', '').strip()
        uploaded = request.files.get('syllabus_file')
        if uploaded and uploaded.filename:
            filename = secure_filename(uploaded.filename)
            file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
            uploaded.save(file_path)
            if filename.lower().endswith(".pdf"):
                raw_text = _extract_text_from_pdf(file_path) or raw_text
            else:
                try:
                    with open(file_path, "r", encoding="utf-8") as handle:
                        raw_text = handle.read()
                except Exception:
                    pass

        topics = []
        projects = []
        if roadmap_type == "career":
            key = _normalize(title)
            match = None
            for template_key in CAREER_TEMPLATES.keys():
                if template_key in key:
                    match = CAREER_TEMPLATES[template_key]
                    break
            if match:
                topics = match["topics"]
                projects = match["projects"]
            else:
                topics = _extract_topics_from_text(raw_text)
        else:
            topics = _extract_topics_from_text(raw_text)

        if not title:
            title = "Dream Roadmap"
        if not topics and roadmap_type == "syllabus":
            flash("Please provide a syllabus text or upload a file with topics.")
            return redirect(url_for('dashboard.create_roadmap'))

        target_date = start_date + timedelta(weeks=timeline_weeks)
        roadmap = Roadmap(
            title=title,
            roadmap_type=roadmap_type,
            source_text=raw_text[:5000],
            start_date=start_date,
            target_date=target_date,
            total_tasks=0,
            completed_tasks=0,
            user_id=session['user_id']
        )
        db.session.add(roadmap)
        db.session.flush()

        task_specs = _build_tasks(roadmap_type, topics, projects, start_date, timeline_weeks)
        for spec in task_specs:
            task = Task(
                title=spec["title"],
                order_index=spec["order_index"],
                due_date=spec["due_date"],
                roadmap_id=roadmap.id
            )
            db.session.add(task)
            db.session.flush()

            resources = _fetch_resources_for_topic(spec["title"].replace("Project: ", ""))
            for res in resources:
                db.session.add(Resource(
                    provider=res["provider"],
                    title=res["title"],
                    url=res["url"],
                    summary=res.get("summary", ""),
                    task_id=task.id
                ))

        roadmap.total_tasks = len(task_specs)
        db.session.commit()
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    return render_template('roadmap_new.html', templates=sorted(CAREER_TEMPLATES.keys()))


@dashboard_bp.route('/roadmap/<int:roadmap_id>')
@login_required
def view_roadmap(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    progress = round((roadmap.completed_tasks / roadmap.total_tasks) * 100, 2) if roadmap.total_tasks else 0
    return render_template('roadmap_view.html', roadmap=roadmap, tasks=tasks, progress=progress)


@dashboard_bp.route('/roadmap/<int:roadmap_id>/task/<int:task_id>/status', methods=['POST'])
@login_required
def update_task_status(roadmap_id, task_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    task = Task.query.get_or_404(task_id)
    if roadmap.user_id != session['user_id'] or task.roadmap_id != roadmap.id:
        return redirect(url_for('dashboard.dashboard'))
    new_status = request.form.get('status', 'todo')
    if new_status not in ["todo", "doing", "done"]:
        new_status = "todo"
    if task.status != new_status:
        task.status = new_status
    roadmap.completed_tasks = Task.query.filter_by(roadmap_id=roadmap.id, status="done").count()
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/delete', methods=['POST'])
@login_required
def delete_roadmap(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    db.session.delete(roadmap)
    db.session.commit()
    return redirect(url_for('dashboard.dashboard'))

