from flask import Blueprint, render_template, request, redirect, session, url_for, current_app, flash, send_file
from extensions import db
from models.models import User, Roadmap, Task, Resource, ResourceFeedback, Checkin
from datetime import datetime, timedelta, date
from werkzeug.utils import secure_filename
from urllib.parse import quote
import os
import re
import csv
import io
import math
import requests
from supabase import create_client
from huggingface_hub import InferenceClient

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
    lines = [l.strip(" -\t") for l in text.splitlines()]
    lines = [l for l in lines if len(l) > 2]
    if len(lines) <= 2:
        parts = re.split(r"[.;]\s+", text)
        lines = [p.strip() for p in parts if len(p.strip()) > 2]
    unique = []
    for item in lines:
        if item.lower() not in [u.lower() for u in unique]:
            unique.append(item)
    return unique[:60]


def _extract_text_from_pdf(file_path):
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        text = []
        for page in reader.pages[:12]:
            text.append(page.extract_text() or "")
        return "\n".join(text).strip()
    except Exception:
        return ""


def _extract_text_from_docx(file_path):
    try:
        from docx import Document
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs]).strip()
    except Exception:
        return ""


def _extract_text_from_image(file_path):
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(file_path)).strip()
    except Exception:
        return ""


def _allowed_file(filename, allowed_exts):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_exts


def _request_session():
    session_obj = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=2)
    session_obj.mount("https://", adapter)
    session_obj.mount("http://", adapter)
    return session_obj


def _safe_get(url, headers=None, params=None):
    try:
        timeout = current_app.config.get("REQUEST_TIMEOUT_SECONDS", 8)
        response = _request_session().get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


def _supabase_client():
    url = current_app.config.get("SUPABASE_URL")
    key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def _ai_extract_topics(text):
    api_key = current_app.config.get("OPENAI_API_KEY")
    model = current_app.config.get("OPENAI_MODEL")
    if not api_key or not model:
        return []
    prompt = (
        "Extract a clean JSON array of unique topic strings from the syllabus text. "
        "Keep each topic short (3-8 words). Return ONLY JSON.\n\n"
        f"Syllabus:\n{text[:8000]}"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": "You extract concise topics from messy syllabi."},
            {"role": "user", "content": prompt}
        ],
        "max_output_tokens": 600
    }
    try:
        timeout = current_app.config.get("REQUEST_TIMEOUT_SECONDS", 8)
        response = _request_session().post("https://api.openai.com/v1/responses", headers=headers, json=payload, timeout=timeout)
        if response.status_code != 200:
            return []
        data = response.json()
        raw = None
        if isinstance(data, dict):
            raw = data.get("output_text")
            if not raw and data.get("output"):
                for item in data["output"]:
                    for content in item.get("content", []):
                        if content.get("type") == "output_text":
                            raw = content.get("text")
                            break
        if not raw:
            return []
        try:
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            return _extract_topics_from_text(raw)
    except Exception:
        return []
    return []


def _hf_extract_topics(text):
    api_key = current_app.config.get("HF_API_KEY")
    model = current_app.config.get("HF_MODEL")
    if not api_key or not model:
        return []
    prompt = (
        "Extract a JSON array of unique topic strings from the syllabus text. "
        "Keep each topic short. Return only JSON.\n\n"
        f"Syllabus:\n{text[:8000]}"
    )
    try:
        client = InferenceClient(model=model, token=api_key)
        response = client.text_generation(prompt, max_new_tokens=400, temperature=0.1)
        import json
        parsed = json.loads(response)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        return []
    return []


def _estimate_difficulty(topic):
    text = topic.lower()
    if any(k in text for k in ["advanced", "optimization", "security", "deep", "architecture"]):
        return "hard"
    if any(k in text for k in ["intro", "basic", "fundamental", "overview"]):
        return "easy"
    return "medium"


def _estimate_hours(topic):
    words = len(topic.split())
    base = 1.5
    extra = min(words * 0.2, 2.0)
    if "project" in topic.lower():
        base += 2.0
    if "capstone" in topic.lower():
        base += 3.0
    return round(base + extra, 1)


def _resource_score(provider):
    scores = {
        "wikipedia": 0.8,
        "crossref": 0.9,
        "github": 0.7,
        "openalex": 0.85,
    }
    return scores.get(provider, 0.6)


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
            "summary": wiki_data.get("extract", ""),
            "score": _resource_score("wikipedia")
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
                    "summary": "Academic reference",
                    "score": _resource_score("crossref")
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
                "summary": repo.get("description", ""),
                "score": _resource_score("github")
            })

    return resources


def _schedule_items(items, start_date, timeline_weeks, hours_per_week, study_days_per_week):
    tasks = []
    if not items:
        items = ["Define milestones", "Gather resources", "Start learning", "Build a mini project"]

    estimated_hours = [_estimate_hours(item) for item in items]
    total_hours = sum(estimated_hours) or 1
    if timeline_weeks and timeline_weeks > 0:
        total_days = max(timeline_weeks * 7, 7)
    else:
        total_days = max(math.ceil(total_hours / max(hours_per_week, 1) * 7), 7)

    current_date = start_date
    for idx, item in enumerate(items):
        share = estimated_hours[idx] / total_hours
        task_days = max(1, math.ceil(total_days * share))
        due_date = current_date + timedelta(days=task_days)
        tasks.append({
            "title": item,
            "order_index": idx + 1,
            "due_date": due_date,
            "difficulty": _estimate_difficulty(item),
            "estimated_hours": estimated_hours[idx]
        })
        current_date = due_date
    return tasks, total_hours, current_date


def _build_tasks(roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week, study_days_per_week):
    all_items = topics[:]
    if roadmap_type == "career":
        for project in projects:
            all_items.append(f"Project: {project}")
    return _schedule_items(all_items, start_date, timeline_weeks, hours_per_week, study_days_per_week)


def _calculate_forecast(roadmap):
    if roadmap.total_tasks == 0:
        return None
    days_elapsed = max((datetime.utcnow().date() - roadmap.start_date).days, 1)
    pace = roadmap.completed_tasks / days_elapsed
    if pace <= 0:
        return None
    remaining = roadmap.total_tasks - roadmap.completed_tasks
    est_days_left = math.ceil(remaining / pace)
    return datetime.utcnow().date() + timedelta(days=est_days_left)


def _update_streak(roadmap, checkin_date):
    if roadmap.last_checkin_date is None:
        roadmap.streak = 1
    else:
        delta = (checkin_date - roadmap.last_checkin_date).days
        if delta == 1:
            roadmap.streak += 1
        elif delta > 1:
            roadmap.streak = 1
    roadmap.last_checkin_date = checkin_date


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
        timeline_weeks = int(request.form.get('timeline_weeks', 0) or 0)
        timeline_weeks = max(0, min(52, timeline_weeks))
        hours_per_week = int(request.form.get('hours_per_week', 6))
        hours_per_week = max(1, min(40, hours_per_week))
        study_days_per_week = int(request.form.get('study_days_per_week', 5))
        study_days_per_week = max(1, min(7, study_days_per_week))
        start_date_str = request.form.get('start_date')
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else datetime.utcnow().date()

        raw_text = request.form.get('source_text', '').strip()
        uploaded = request.files.get('syllabus_file')
        if uploaded and uploaded.filename:
            if not _allowed_file(uploaded.filename, {"pdf", "txt", "docx", "png", "jpg", "jpeg", "bmp", "tiff"}):
                flash("Unsupported file type. Upload PDF, TXT, DOCX, or image files.")
                return redirect(url_for('dashboard.create_roadmap'))
            filename = secure_filename(uploaded.filename)
            unique_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
            file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], unique_name)
            uploaded.save(file_path)
            ext = filename.lower()
            if ext.endswith(".pdf"):
                raw_text = _extract_text_from_pdf(file_path) or raw_text
            elif ext.endswith(".docx"):
                raw_text = _extract_text_from_docx(file_path) or raw_text
            elif ext.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff")):
                raw_text = _extract_text_from_image(file_path) or raw_text
            else:
                try:
                    with open(file_path, "r", encoding="utf-8") as handle:
                        raw_text = handle.read()
                except Exception:
                    pass

        topics = []
        projects = []
        use_ai = request.form.get('use_ai') == 'on'
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

        if (use_ai or current_app.config.get("AI_TOPIC_EXTRACTION_ENABLED")) and raw_text:
            ai_topics = _ai_extract_topics(raw_text)
            if not ai_topics:
                ai_topics = _hf_extract_topics(raw_text)
            if ai_topics:
                topics = ai_topics

        if not title:
            title = "Dream Roadmap"
        if not topics and roadmap_type == "syllabus":
            flash("Please provide a syllabus text or upload a file with topics.")
            return redirect(url_for('dashboard.create_roadmap'))

        task_specs, total_hours, computed_end = _build_tasks(
            roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week, study_days_per_week
        )
        target_date = computed_end

        roadmap = Roadmap(
            title=title,
            roadmap_type=roadmap_type,
            source_text=raw_text[:5000],
            start_date=start_date,
            target_date=target_date,
            total_tasks=len(task_specs),
            completed_tasks=0,
            total_hours_est=total_hours,
            hours_per_week=hours_per_week,
            study_days_per_week=study_days_per_week,
            timezone=request.form.get('timezone', 'UTC'),
            user_id=session['user_id']
        )
        db.session.add(roadmap)
        db.session.flush()

        for spec in task_specs:
            task = Task(
                title=spec["title"],
                order_index=spec["order_index"],
                due_date=spec["due_date"],
                difficulty=spec["difficulty"],
                estimated_hours=spec["estimated_hours"],
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
                    score=res.get("score", 0.0),
                    task_id=task.id
                ))
            task.last_resource_refresh = datetime.utcnow()

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
    forecast = _calculate_forecast(roadmap)
    last_checkin = roadmap.last_checkin_date.strftime("%Y-%m-%d") if roadmap.last_checkin_date else "None"
    resources_map = {}
    for task in tasks:
        resources_map[task.id] = sorted(
            task.resources,
            key=lambda r: (-(r.rating_avg + r.score), r.flagged_count)
        )
    return render_template(
        'roadmap_view.html',
        roadmap=roadmap,
        tasks=tasks,
        progress=progress,
        forecast=forecast,
        last_checkin=last_checkin,
        resources_map=resources_map
    )


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
    task.status = new_status

    task.completion_type = request.form.get('completion_type', 'planned')
    if task.completion_type not in ["planned", "alternative"]:
        task.completion_type = "planned"
    task.notes = request.form.get('notes', '').strip() or None

    try:
        task.actual_hours = float(request.form.get('actual_hours', task.actual_hours or 0))
    except ValueError:
        pass

    evidence = request.files.get('evidence')
    if evidence and evidence.filename:
        if not _allowed_file(evidence.filename, {"pdf", "png", "jpg", "jpeg", "txt", "docx"}):
            flash("Unsupported evidence file type.")
            return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
        filename = secure_filename(evidence.filename)
        unique_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
        storage_client = _supabase_client()
        if storage_client:
            bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "evidence")
            storage_path = f"{session['user_id']}/{roadmap.id}/{task.id}/{unique_name}"
            try:
                storage_client.storage.from_(bucket).upload(
                    storage_path,
                    evidence.stream.read(),
                    {"content-type": evidence.mimetype or "application/octet-stream"}
                )
                task.evidence_path = storage_path
            except Exception:
                flash("Failed to upload evidence to storage.")
                return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
        else:
            file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], unique_name)
            evidence.save(file_path)
            task.evidence_path = unique_name

    if new_status == "done":
        task.completed_at = datetime.utcnow()
    roadmap.completed_tasks = Task.query.filter_by(roadmap_id=roadmap.id, status="done").count()
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/checkin', methods=['POST'])
@login_required
def checkin(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    minutes = int(request.form.get('minutes', 0) or 0)
    note = request.form.get('note', '').strip() or None
    today = date.today()
    checkin = Checkin(checkin_date=today, minutes=minutes, note=note, roadmap_id=roadmap.id)
    db.session.add(checkin)
    _update_streak(roadmap, today)
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/task/<int:task_id>/refresh', methods=['POST'])
@login_required
def refresh_resources(roadmap_id, task_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    task = Task.query.get_or_404(task_id)
    if roadmap.user_id != session['user_id'] or task.roadmap_id != roadmap.id:
        return redirect(url_for('dashboard.dashboard'))

    refresh_days = current_app.config.get("RESOURCE_REFRESH_DAYS", 7)
    if task.last_resource_refresh and (datetime.utcnow() - task.last_resource_refresh).days < refresh_days:
        flash("Resources were refreshed recently. Try again later.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    Resource.query.filter_by(task_id=task.id).delete()
    resources = _fetch_resources_for_topic(task.title.replace("Project: ", ""))
    for res in resources:
        db.session.add(Resource(
            provider=res["provider"],
            title=res["title"],
            url=res["url"],
            summary=res.get("summary", ""),
            score=res.get("score", 0.0),
            task_id=task.id
        ))
    task.last_resource_refresh = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/resource/<int:resource_id>/feedback', methods=['POST'])
@login_required
def resource_feedback(roadmap_id, resource_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    resource = Resource.query.get_or_404(resource_id)
    if roadmap.user_id != session['user_id'] or resource.task.roadmap_id != roadmap.id:
        return redirect(url_for('dashboard.dashboard'))
    rating = request.form.get('rating')
    flagged = request.form.get('flagged') == 'true'
    comment = request.form.get('comment', '').strip() or None
    feedback = ResourceFeedback(
        rating=int(rating) if rating else None,
        flagged=flagged,
        comment=comment,
        resource_id=resource.id
    )
    db.session.add(feedback)
    if rating:
        rating_val = int(rating)
        total = resource.rating_avg * resource.rating_count + rating_val
        resource.rating_count += 1
        resource.rating_avg = round(total / resource.rating_count, 2)
    if flagged:
        resource.flagged_count += 1
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/export.csv')
@login_required
def export_csv(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Task", "Status", "Due Date", "Estimated Hours", "Actual Hours", "Difficulty"])
    for task in tasks:
        writer.writerow([
            task.title,
            task.status,
            task.due_date,
            task.estimated_hours,
            task.actual_hours,
            task.difficulty
        ])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")), mimetype="text/csv",
                     as_attachment=True, download_name="roadmap.csv")


@dashboard_bp.route('/roadmap/<int:roadmap_id>/export.ics')
@login_required
def export_ics(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DreamsIntoReality//Roadmap//EN"]
    for task in tasks:
        if not task.due_date:
            continue
        dt = task.due_date.strftime("%Y%m%d")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:task-{task.id}@dreams",
            f"DTSTART;VALUE=DATE:{dt}",
            f"DTEND;VALUE=DATE:{dt}",
            f"SUMMARY:{task.title}",
            "END:VEVENT"
        ])
    lines.append("END:VCALENDAR")
    content = "\n".join(lines)
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/calendar",
                     as_attachment=True, download_name="roadmap.ics")


@dashboard_bp.route('/roadmap/<int:roadmap_id>/rebalance', methods=['POST'])
@login_required
def rebalance(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    remaining_tasks = Task.query.filter_by(roadmap_id=roadmap.id).filter(Task.status != "done").order_by(Task.order_index.asc()).all()
    if not remaining_tasks:
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    start_date = datetime.utcnow().date()
    timeline_weeks = int(request.form.get('timeline_weeks', 0) or 0)
    titles = [t.title for t in remaining_tasks]
    task_specs, total_hours, computed_end = _schedule_items(
        titles,
        start_date,
        timeline_weeks,
        roadmap.hours_per_week,
        roadmap.study_days_per_week
    )
    for idx, spec in enumerate(task_specs):
        if idx >= len(remaining_tasks):
            break
        task = remaining_tasks[idx]
        task.due_date = spec["due_date"]
        task.estimated_hours = spec["estimated_hours"]
    roadmap.target_date = computed_end
    roadmap.total_hours_est = total_hours
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


@dashboard_bp.route('/uploads/<path:filename>')
@login_required
def get_upload(filename):
    storage_client = _supabase_client()
    if storage_client and "/" in filename:
        bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "evidence")
        expires = current_app.config.get("SIGNED_URL_EXPIRES_SECONDS", 600)
        try:
            signed = storage_client.storage.from_(bucket).create_signed_url(filename, expires)
            signed_url = signed.get("signedURL") or signed.get("signed_url")
            if signed_url:
                return redirect(signed_url)
        except Exception:
            pass
    safe_name = secure_filename(filename)
    file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], safe_name)
    if not os.path.isfile(file_path):
        return redirect(url_for('dashboard.dashboard'))
    return send_file(file_path, as_attachment=True)
