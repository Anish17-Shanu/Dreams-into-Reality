from flask import Blueprint, render_template, request, redirect, session, url_for, current_app, flash, send_file
from extensions import db
from models.models import User, Roadmap, Task, Resource, ResourceFeedback, Checkin, Question, QuestionAttempt, PyqCompletion, MockTestSchedule, QuizResult
from datetime import datetime, timedelta, date, UTC
from werkzeug.utils import secure_filename
from urllib.parse import quote
import os
import re
import csv
import io
import math
import requests
import threading
from supabase import create_client
from sqlalchemy import inspect

dashboard_bp = Blueprint('dashboard', __name__)

RECENT_IMPROVEMENTS = [
    {"title": "Safer roadmap generation", "detail": "Creation flow now protects against fragile schema-dependent crashes."},
    {"title": "Adaptive recovery guidance", "detail": "Plans now explain how to catch up, rebalance, or reduce stress without guessing."},
    {"title": "Sharper execution view", "detail": "Roadmaps surface today, this week, risks, momentum, and monthly progress in one place."},
]


def _available_tables():
    try:
        return set(inspect(db.engine).get_table_names())
    except Exception:
        return set()


def _has_table(table_name):
    return table_name in _available_tables()


def _normalize_pace_mode(value):
    value = (value or "steady").strip().lower()
    if value in {"burnout_safe", "steady", "sprint"}:
        return value
    return "steady"


def _pace_label(value):
    labels = {
        "burnout_safe": "Burnout-safe",
        "steady": "Steady",
        "sprint": "Fast-track",
    }
    return labels.get(_normalize_pace_mode(value), "Steady")


def _utc_now():
    return datetime.now(UTC)


def _utc_today():
    return _utc_now().date()

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

UPSC_TEMPLATE_TOPICS = [
    "Civil Services Preliminary: General Studies Paper I",
    "Civil Services Preliminary: CSAT",
    "Civil Services Mains: Essay",
    "Civil Services Mains: General Studies I",
    "Civil Services Mains: General Studies II",
    "Civil Services Mains: General Studies III",
    "Civil Services Mains: General Studies IV (Ethics)",
    "Civil Services Mains: Optional Subject (choose one)",
    "Indian Forest Service Preliminary: GS + CSAT",
    "Indian Forest Service Mains: Optional Subject",
    "Combined Defence Services: English",
    "Combined Defence Services: General Knowledge",
    "Combined Defence Services: Elementary Mathematics",
    "National Defence Academy: Mathematics",
    "National Defence Academy: General Ability",
    "CAPF (AC): General Ability & Intelligence",
    "Engineering Services: General Studies & Engineering Aptitude",
    "Engineering Services: Technical Papers (choose branch)",
    "IES/ISS: Statistics/Economics Papers",
    "Combined Medical Services: Paper I",
    "Combined Medical Services: Paper II",
    "Geologist/Geophysicist: Paper I-IV"
]

UPSC_RESOURCES = [
    {"title": "UPSC Examination Calendar", "url": "https://upsc.gov.in/examinations/exam-calendar", "provider": "upsc"},
    {"title": "UPSC Previous Question Papers", "url": "https://upsc.gov.in/examinations/previous-question-papers", "provider": "upsc"},
    {"title": "UPSC Revised Syllabus & Scheme", "url": "https://upsc.gov.in/examinations/revised-syllabus-scheme", "provider": "upsc"},
    {"title": "UPSC Model Question and Answer Booklets", "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets", "provider": "upsc"},
    {"title": "Press Information Bureau", "url": "https://pib.gov.in", "provider": "official"},
    {"title": "PRS Legislative Research", "url": "https://prsindia.org", "provider": "research"},
    {"title": "NCERT Textbooks Portal", "url": "https://ncert.nic.in/textbook.php", "provider": "ncert"},
]

UPSC_CURATED_RESOURCES = [
    {
        "title": "UPSC Revised Syllabus and Scheme",
        "url": "https://upsc.gov.in/examinations/revised-syllabus-scheme",
        "provider": "upsc",
        "bucket": "Official source",
        "tags": ["Official", "All stages", "Must use"],
        "use_case": "Start every subject from the official syllabus so your preparation stays aligned with the exam.",
        "topics": ["strategy", "foundation", "prelims", "mains", "interview", "optional"],
    },
    {
        "title": "UPSC Previous Question Papers",
        "url": "https://upsc.gov.in/examinations/previous-question-papers",
        "provider": "upsc",
        "bucket": "Official source",
        "tags": ["Official", "PYQ", "High value"],
        "use_case": "Use PYQs to understand pattern, question language, and topic priority before adding new study material.",
        "topics": ["pyq", "prelims", "mains", "essay", "optional", "csat"],
    },
    {
        "title": "UPSC Exam Calendar",
        "url": "https://upsc.gov.in/examinations/exam-calendar",
        "provider": "upsc",
        "bucket": "Official source",
        "tags": ["Official", "Timeline"],
        "use_case": "Anchor your milestones, mock schedule, and revision buffers around official dates.",
        "topics": ["strategy", "timeline", "prelims", "mains", "interview"],
    },
    {
        "title": "NCERT Textbooks Portal",
        "url": "https://ncert.nic.in/textbook.php",
        "provider": "ncert",
        "bucket": "Start here",
        "tags": ["Beginner", "Foundation", "Static subjects"],
        "use_case": "Best starting point for core concepts before moving to advanced books or current-affairs integration.",
        "topics": ["foundation", "history", "geography", "science", "economy", "environment", "society"],
    },
    {
        "title": "Press Information Bureau",
        "url": "https://pib.gov.in",
        "provider": "official",
        "bucket": "Official source",
        "tags": ["Current affairs", "Government source"],
        "use_case": "Use for authentic current-affairs notes and examples, especially for mains enrichment and interview balance.",
        "topics": ["current affairs", "governance", "economy", "international relations", "interview", "mains"],
    },
    {
        "title": "PRS Legislative Research",
        "url": "https://prsindia.org",
        "provider": "research",
        "bucket": "Deep study",
        "tags": ["Governance", "Bills", "Analysis"],
        "use_case": "Excellent for governance, policy, Parliament, and issue-based mains answers with clarity and structure.",
        "topics": ["polity", "governance", "constitution", "social justice", "international relations", "mains"],
    },
    {
        "title": "Ministry of Environment, Forest and Climate Change",
        "url": "https://moef.gov.in",
        "provider": "official",
        "bucket": "Official source",
        "tags": ["Environment", "Official"],
        "use_case": "Useful for environment, biodiversity, schemes, conventions, and current updates.",
        "topics": ["environment", "ecology", "prelims", "mains"],
    },
    {
        "title": "Reserve Bank of India Publications",
        "url": "https://www.rbi.org.in",
        "provider": "official",
        "bucket": "Deep study",
        "tags": ["Economy", "Official"],
        "use_case": "Use to strengthen economy basics, monetary policy understanding, and mains examples.",
        "topics": ["economy", "budget", "banking", "prelims", "mains"],
    },
    {
        "title": "India Year Book and Government Portals",
        "url": "https://www.india.gov.in",
        "provider": "official",
        "bucket": "Quick revision",
        "tags": ["Schemes", "Government", "Revision"],
        "use_case": "Helpful for quick government facts, ministries, schemes, and factual brushing up.",
        "topics": ["governance", "social justice", "schemes", "interview", "revision"],
    },
    {
        "title": "ISRO Official Website",
        "url": "https://www.isro.gov.in",
        "provider": "official",
        "bucket": "Official source",
        "tags": ["Science and Tech", "Official"],
        "use_case": "Strong source for science and tech examples, space updates, and interview-ready factual grounding.",
        "topics": ["science", "technology", "prelims", "mains", "interview"],
    },
    {
        "title": "NITI Aayog Reports",
        "url": "https://www.niti.gov.in",
        "provider": "official",
        "bucket": "Deep study",
        "tags": ["Policy", "Development", "Mains"],
        "use_case": "Useful for policy framing, statistics, reforms, and value-added mains examples.",
        "topics": ["economy", "governance", "social justice", "agriculture", "mains", "essay"],
    },
    {
        "title": "Ministry of External Affairs",
        "url": "https://www.mea.gov.in",
        "provider": "official",
        "bucket": "Official source",
        "tags": ["International Relations", "Official"],
        "use_case": "Best official source for India's foreign policy positions and recent bilateral developments.",
        "topics": ["international relations", "interview", "mains"],
    },
    {
        "title": "Ethics Case Study Practice Notes",
        "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets",
        "provider": "upsc",
        "bucket": "Quick revision",
        "tags": ["Ethics", "Model answers"],
        "use_case": "Use to understand the structure and tone expected in official-style answers and case handling.",
        "topics": ["ethics", "answer writing", "mains"],
    },
]

UPSC_HAND_TUNED_PACKS = {
    "foundation": {
        "label": "Foundation and strategy pack",
        "resources": [
            {
                "title": "UPSC Revised Syllabus and Scheme",
                "url": "https://upsc.gov.in/examinations/revised-syllabus-scheme",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Foundation", "Official", "Must use"],
                "use_case": "Use as the master checklist before choosing books or courses.",
            },
            {
                "title": "UPSC Previous Question Papers",
                "url": "https://upsc.gov.in/examinations/previous-question-papers",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Foundation", "PYQ", "Pattern"],
                "use_case": "Use early to understand the exam before over-consuming resources.",
            },
            {
                "title": "NCERT Textbooks Portal",
                "url": "https://ncert.nic.in/textbook.php",
                "provider": "ncert",
                "bucket": "Start here",
                "tags": ["Foundation", "Beginner"],
                "use_case": "Best for building the conceptual base needed for both prelims and mains.",
            },
        ],
    },
    "prelims_gs": {
        "label": "Prelims GS pack",
        "resources": [
            {
                "title": "UPSC Previous Question Papers",
                "url": "https://upsc.gov.in/examinations/previous-question-papers",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Prelims", "PYQ", "Must use"],
                "use_case": "Use for elimination practice and trend awareness.",
            },
            {
                "title": "NCERT Textbooks Portal",
                "url": "https://ncert.nic.in/textbook.php",
                "provider": "ncert",
                "bucket": "Start here",
                "tags": ["Prelims", "Static"],
                "use_case": "Best static base for history, geography, science, and environment.",
            },
            {
                "title": "Press Information Bureau",
                "url": "https://pib.gov.in",
                "provider": "official",
                "bucket": "Quick revision",
                "tags": ["Prelims", "Current affairs"],
                "use_case": "Use selectively for current-affairs notes tied to government action and schemes.",
            },
        ],
    },
    "csat": {
        "label": "CSAT pack",
        "resources": [
            {
                "title": "UPSC Previous Question Papers",
                "url": "https://upsc.gov.in/examinations/previous-question-papers",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["CSAT", "PYQ"],
                "use_case": "Practice directly from official papers to understand actual CSAT pressure.",
            },
            {
                "title": "UPSC Model Question and Answer Booklets",
                "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets",
                "provider": "upsc",
                "bucket": "Quick revision",
                "tags": ["CSAT", "Format"],
                "use_case": "Useful to get comfortable with official-style presentation and response formats.",
            },
        ],
    },
    "essay": {
        "label": "Essay pack",
        "resources": [
            {
                "title": "NITI Aayog Reports",
                "url": "https://www.niti.gov.in",
                "provider": "official",
                "bucket": "Deep study",
                "tags": ["Essay", "Examples", "Policy"],
                "use_case": "Strong source for balanced examples, policy references, and issue framing.",
            },
            {
                "title": "Press Information Bureau",
                "url": "https://pib.gov.in",
                "provider": "official",
                "bucket": "Quick revision",
                "tags": ["Essay", "Current affairs"],
                "use_case": "Useful for fresh examples and current issue angles.",
            },
        ],
    },
    "gs1": {
        "label": "GS1 pack",
        "resources": [
            {
                "title": "NCERT Textbooks Portal",
                "url": "https://ncert.nic.in/textbook.php",
                "provider": "ncert",
                "bucket": "Start here",
                "tags": ["GS1", "History", "Geography"],
                "use_case": "Best base for culture, society, history, and geography preparation.",
            },
            {
                "title": "UPSC Previous Question Papers",
                "url": "https://upsc.gov.in/examinations/previous-question-papers",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["GS1", "PYQ"],
                "use_case": "Use to understand how UPSC frames GS1 themes and answer demand.",
            },
        ],
    },
    "gs2": {
        "label": "GS2 pack",
        "resources": [
            {
                "title": "PRS Legislative Research",
                "url": "https://prsindia.org",
                "provider": "research",
                "bucket": "Deep study",
                "tags": ["GS2", "Governance", "Bills"],
                "use_case": "Excellent for governance, Parliament, federalism, and policy analysis.",
            },
            {
                "title": "Ministry of External Affairs",
                "url": "https://www.mea.gov.in",
                "provider": "official",
                "bucket": "Official source",
                "tags": ["GS2", "IR", "Official"],
                "use_case": "Best official reference for international relations and foreign policy issues.",
            },
            {
                "title": "India Year Book and Government Portals",
                "url": "https://www.india.gov.in",
                "provider": "official",
                "bucket": "Quick revision",
                "tags": ["GS2", "Schemes", "Government"],
                "use_case": "Useful for ministries, schemes, and quick factual support.",
            },
        ],
    },
    "gs3": {
        "label": "GS3 pack",
        "resources": [
            {
                "title": "Reserve Bank of India Publications",
                "url": "https://www.rbi.org.in",
                "provider": "official",
                "bucket": "Deep study",
                "tags": ["GS3", "Economy", "Official"],
                "use_case": "Strong source for economy, monetary policy, inflation, and banking.",
            },
            {
                "title": "Ministry of Environment, Forest and Climate Change",
                "url": "https://moef.gov.in",
                "provider": "official",
                "bucket": "Official source",
                "tags": ["GS3", "Environment", "Official"],
                "use_case": "Use for environment, conventions, biodiversity, and policy updates.",
            },
            {
                "title": "ISRO Official Website",
                "url": "https://www.isro.gov.in",
                "provider": "official",
                "bucket": "Official source",
                "tags": ["GS3", "Science and Tech", "Official"],
                "use_case": "Best for space and technology examples with factual reliability.",
            },
            {
                "title": "NITI Aayog Reports",
                "url": "https://www.niti.gov.in",
                "provider": "official",
                "bucket": "Deep study",
                "tags": ["GS3", "Development", "Data points"],
                "use_case": "Useful for reforms, agriculture, innovation, and development examples.",
            },
        ],
    },
    "gs4": {
        "label": "GS4 ethics pack",
        "resources": [
            {
                "title": "UPSC Model Question and Answer Booklets",
                "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["GS4", "Ethics", "Model answers"],
                "use_case": "Use to understand tone, structure, and expectation in official-style answers.",
            },
            {
                "title": "Ethics Case Study Practice Notes",
                "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets",
                "provider": "upsc",
                "bucket": "Quick revision",
                "tags": ["GS4", "Case studies"],
                "use_case": "Good for building a quick revision loop around ethics case study handling.",
            },
        ],
    },
    "answer_writing": {
        "label": "Answer writing pack",
        "resources": [
            {
                "title": "UPSC Previous Question Papers",
                "url": "https://upsc.gov.in/examinations/previous-question-papers",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Answer writing", "PYQ"],
                "use_case": "Write from actual PYQs instead of generic prompts whenever possible.",
            },
            {
                "title": "UPSC Model Question and Answer Booklets",
                "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Answer writing", "Model answers"],
                "use_case": "Best reference for structure, presentation, and clarity.",
            },
        ],
    },
    "interview": {
        "label": "Interview pack",
        "resources": [
            {
                "title": "Press Information Bureau",
                "url": "https://pib.gov.in",
                "provider": "official",
                "bucket": "Official source",
                "tags": ["Interview", "Current affairs"],
                "use_case": "Use for authentic current-affairs grounding and balanced speaking points.",
            },
            {
                "title": "Ministry of External Affairs",
                "url": "https://www.mea.gov.in",
                "provider": "official",
                "bucket": "Deep study",
                "tags": ["Interview", "IR", "Official"],
                "use_case": "Helps build balanced and informed answers on international issues.",
            },
            {
                "title": "India Year Book and Government Portals",
                "url": "https://www.india.gov.in",
                "provider": "official",
                "bucket": "Quick revision",
                "tags": ["Interview", "Government", "Facts"],
                "use_case": "Useful for factual brushing up before mock interviews and profile questions.",
            },
        ],
    },
    "optional": {
        "label": "Optional workflow pack",
        "resources": [
            {
                "title": "UPSC Revised Syllabus and Scheme",
                "url": "https://upsc.gov.in/examinations/revised-syllabus-scheme",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Optional", "Official", "Must use"],
                "use_case": "Always anchor optional preparation to the official syllabus first.",
            },
            {
                "title": "UPSC Previous Question Papers",
                "url": "https://upsc.gov.in/examinations/previous-question-papers",
                "provider": "upsc",
                "bucket": "Official source",
                "tags": ["Optional", "PYQ", "Must use"],
                "use_case": "Use PYQs to identify recurring themes and answer demand in the optional subject.",
            },
        ],
    },
}

UPSC_EXAMS = [
    "Civil Services Prelims",
    "Civil Services Mains",
    "Indian Forest Service",
    "Combined Defence Services",
    "National Defence Academy",
    "CAPF (AC)",
    "Engineering Services",
    "IES/ISS",
    "Combined Medical Services",
    "Geo-Scientist"
]

UPSC_STAGE_TOPICS = {
    "full_journey": [
        "UPSC exam strategy and attempt planning",
        "NCERT foundation build-up",
        "Current affairs system and revision notes",
        "Indian Polity and Constitution",
        "History of India and freedom struggle",
        "Indian and world geography",
        "Indian economy and budgeting",
        "Environment and ecology",
        "Science and technology for UPSC",
        "Internal security and disaster management",
        "International relations",
        "Governance and social justice",
        "Ethics, integrity and aptitude",
        "Essay writing framework",
        "CSAT aptitude and comprehension",
        "Optional subject strategy",
        "Answer writing and mains enrichment",
        "Prelims PYQ analysis",
        "Mains PYQ analysis",
        "Revision cycles and full-length mocks",
        "Interview preparation and DAF based questions",
    ],
    "prelims": [
        "NCERT foundation build-up",
        "Current affairs system and revision notes",
        "Indian Polity and Constitution",
        "History of India and freedom struggle",
        "Indian and world geography",
        "Indian economy and budgeting",
        "Environment and ecology",
        "Science and technology for UPSC",
        "CSAT aptitude and comprehension",
        "Prelims PYQ analysis",
        "Sectional prelims tests",
        "Full-length prelims mocks and revision",
    ],
    "mains": [
        "Current affairs to mains notes conversion",
        "Essay writing framework",
        "General Studies I answer writing",
        "General Studies II answer writing",
        "General Studies III answer writing",
        "General Studies IV ethics case studies",
        "Optional subject strategy",
        "Mains PYQ analysis",
        "Value-added notes and examples",
        "Full-length mains mocks and revision",
    ],
    "interview": [
        "DAF analysis and profile mapping",
        "Current affairs for interview",
        "Opinion framing and balanced answers",
        "Mock interview practice",
        "Communication, posture and confidence",
    ],
}

UPSC_SUBJECT_LIBRARY = {
    "foundation": {
        "label": "Foundation and Strategy",
        "topics": [
            "UPSC exam strategy and attempt planning",
            "NCERT foundation build-up",
            "Current affairs system and revision notes",
            "Revision cycles and productivity system",
        ],
    },
    "prelims_gs": {
        "label": "Prelims GS",
        "topics": [
            "Indian Polity and Constitution",
            "History of India and freedom struggle",
            "Indian and world geography",
            "Indian economy and budgeting",
            "Environment and ecology",
            "Science and technology for UPSC",
            "Prelims PYQ analysis",
        ],
    },
    "csat": {
        "label": "CSAT",
        "topics": [
            "CSAT aptitude and comprehension",
            "Reasoning and decision making",
            "Basic numeracy and data interpretation",
        ],
    },
    "essay": {
        "label": "Essay",
        "topics": [
            "Essay writing framework",
            "Essay brainstorming and outline practice",
            "Essay introductions, arguments, and conclusions",
        ],
    },
    "gs1": {
        "label": "GS Paper I",
        "topics": [
            "Indian heritage and culture",
            "Modern Indian history",
            "World history basics",
            "Indian society and social issues",
            "Physical and human geography",
        ],
    },
    "gs2": {
        "label": "GS Paper II",
        "topics": [
            "Governance and social justice",
            "Indian Polity and Constitution",
            "Parliament, judiciary, and federalism",
            "International relations",
        ],
    },
    "gs3": {
        "label": "GS Paper III",
        "topics": [
            "Indian economy and budgeting",
            "Agriculture and food processing",
            "Science and technology for UPSC",
            "Environment and ecology",
            "Internal security and disaster management",
        ],
    },
    "gs4": {
        "label": "GS Paper IV (Ethics)",
        "topics": [
            "Ethics, integrity and aptitude",
            "Case study solving for ethics",
            "Thinkers, examples, and value frameworks",
        ],
    },
    "answer_writing": {
        "label": "Answer Writing",
        "topics": [
            "Answer writing and mains enrichment",
            "Value-added notes and examples",
            "Time-bound answer practice",
        ],
    },
    "interview": {
        "label": "Interview",
        "topics": [
            "Interview preparation and DAF based questions",
            "Current affairs for interview",
            "Opinion framing and balanced answers",
            "Communication, posture and confidence",
        ],
    },
}

UPSC_DEFAULT_SUBJECTS_BY_FOCUS = {
    "full_journey": ["foundation", "prelims_gs", "csat", "essay", "gs1", "gs2", "gs3", "gs4", "answer_writing", "interview"],
    "prelims": ["foundation", "prelims_gs", "csat"],
    "mains": ["foundation", "essay", "gs1", "gs2", "gs3", "gs4", "answer_writing"],
    "interview": ["foundation", "interview"],
}

OPENTDB_API = "https://opentdb.com/api.php"

UPSC_OFFICIAL_GUIDANCE = {
    "full_journey": [
        "Anchor preparation on the official UPSC syllabus, previous year papers, and exam calendar.",
        "Split the journey into foundation, prelims accuracy, mains answer writing, and interview composure.",
        "Keep one revision system, one PYQ tracker, and one mock-analysis loop across the full cycle.",
    ],
    "prelims": [
        "Prioritize static GS coverage, CSAT safety, and elimination practice from PYQs and mocks.",
        "Build weekly revision blocks and test-review sessions instead of only adding fresh sources.",
        "Use official UPSC previous year papers to calibrate difficulty and trend awareness.",
    ],
    "mains": [
        "Translate current affairs into issue-wise notes, examples, and answer-ready frameworks.",
        "Train with timed answers, essay structure, ethics case studies, and value-add examples.",
        "Review UPSC syllabus keywords and PYQs to avoid generic content drift.",
    ],
    "interview": [
        "Map DAF themes, hometown, graduation, work experience, and current affairs into question banks.",
        "Practice balanced responses, body language, and short structured speaking drills.",
        "Keep preparation rooted in official notifications, your profile, and recent national issues.",
    ],
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


def _safe_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _safe_date(value, fallback=None):
    if not value:
        return fallback or _utc_today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback or _utc_today()


def _embed_plan_preferences(raw_text, pace_mode):
    pace_mode = _normalize_pace_mode(pace_mode)
    base = (raw_text or "").strip()
    if "Pace Mode:" in base:
        return base
    suffix = f"Pace Mode: {_pace_label(pace_mode)}"
    return f"{base}\n{suffix}".strip()


def _append_metadata_line(raw_text, label, value):
    value = (value or "").strip()
    if not value:
        return raw_text
    base = (raw_text or "").strip()
    if f"{label}:" in base:
        return base
    return f"{base}\n{label}: {value}".strip()


def _extract_metadata_value(source_text, label, default=""):
    match = re.search(rf"{re.escape(label)}:\s*(.+)", source_text or "", flags=re.IGNORECASE)
    if not match:
        return default
    return match.group(1).strip()


def _extract_pace_mode_from_source_text(source_text):
    label = _normalize(_extract_metadata_value(source_text, "Pace Mode", "steady"))
    if "burnout" in label or "safe" in label:
        return "burnout_safe"
    if "fast" in label or "sprint" in label:
        return "sprint"
    return "steady"


def _extract_profile_from_source_text(source_text):
    return {
        "current_level": _extract_metadata_value(source_text, "Current Level", "beginner"),
        "deadline_pressure": _extract_metadata_value(source_text, "Deadline Pressure", "moderate"),
        "confidence_level": _extract_metadata_value(source_text, "Confidence Level", "growing"),
        "weak_areas": _extract_metadata_value(source_text, "Weak Areas", ""),
        "workflow_mode": _extract_metadata_value(source_text, "Workflow Mode", "normal"),
        "target_outcome": _extract_metadata_value(source_text, "Target Outcome", ""),
    }


def _extract_topics_from_text(text):
    if not text:
        return []
    return _extract_topics_rulebased(text)


def _extract_topics_rulebased(text):
    if not text:
        return []
    candidates = []
    lines = [l.strip() for l in text.splitlines() if l and l.strip()]

    stop_phrases = [
        "course objective", "course objectives", "course outcome", "course outcomes",
        "learning outcome", "learning outcomes", "teaching scheme", "examination scheme",
        "grading", "evaluation", "assessment", "textbook", "reference book",
        "credits", "marks", "attendance", "prerequisite", "prerequisites",
        "instructions", "note:", "notes:", "recommended", "required reading",
        "syllabus", "syllabi", "course contents", "course content", "list of experiments",
    ]
    noise_words = {"introduction", "overview", "basics", "fundamentals", "general"}

    def _is_noise(line_lower):
        return any(phrase in line_lower for phrase in stop_phrases)

    def _clean_heading(raw):
        cleaned = raw.strip(" \t-*")
        cleaned = re.sub(
            r"^(unit|module|chapter|week|topic|section|part)\s*\d+[a-zA-Z]*[:\).\-\s]*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"^\(?[0-9ivxlcdm]+[\)\.\-:]*\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^[A-Za-z][\)\.\-:]\s*", "", cleaned)
        return cleaned.strip()

    def _push_candidate(item):
        if not item:
            return
        normalized = re.sub(r"\s+", " ", item).strip(" ,;:-")
        if not normalized:
            return
        if not any(ch.isalpha() for ch in normalized):
            return
        words = normalized.split()
        if len(words) > 10:
            return
        if len(words) == 1:
            if len(normalized) < 5 or normalized.lower() in noise_words:
                return
        elif len(words) < 2:
            return
        if len(normalized) > 90:
            return
        candidates.append(normalized)

    for line in lines:
        line_lower = line.lower()
        if _is_noise(line_lower):
            continue

        cleaned = _clean_heading(line)

        if ":" in cleaned and len(cleaned.split(":", 1)[0].split()) <= 3:
            right = cleaned.split(":", 1)[1].strip()
            _push_candidate(right)
            continue

        if len(cleaned) <= 140 and (";" in cleaned or "," in cleaned):
            parts = re.split(r"[;,]", cleaned)
            for part in parts:
                _push_candidate(_clean_heading(part))
            continue

        if " - " in cleaned:
            left, right = [p.strip() for p in cleaned.split(" - ", 1)]
            _push_candidate(right or left)
            continue

        _push_candidate(cleaned)

    unique = []
    seen = set()
    for item in candidates:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:80]



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


def _safe_get_text(url, headers=None, params=None):
    try:
        timeout = current_app.config.get("REQUEST_TIMEOUT_SECONDS", 8)
        response = _request_session().get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.text
    except Exception:
        return None
    return None


def _extract_labels_from_obj(obj):
    labels = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ["preferredLabel", "prefLabel", "title", "name"]:
                if isinstance(value, dict):
                    labels.extend([v for v in value.values() if isinstance(v, str)])
                elif isinstance(value, str):
                    labels.append(value)
            else:
                labels.extend(_extract_labels_from_obj(value))
    elif isinstance(obj, list):
        for item in obj:
            labels.extend(_extract_labels_from_obj(item))
    return labels


def _fetch_career_template_esco(query):
    base = current_app.config.get("ESCO_API_BASE", "https://ec.europa.eu/esco/api")
    headers = {"User-Agent": current_app.config.get("WIKIPEDIA_USER_AGENT")}
    search_params = {
        "type": "occupation",
        "text": query,
        "language": "en",
        "limit": 1,
        "full": "false"
    }
    search_url = f"{base}/search"
    search_data = _safe_get(search_url, headers=headers, params=search_params)
    if not search_data:
        return []

    occupation_uri = None
    if isinstance(search_data, dict):
        if "results" in search_data and isinstance(search_data["results"], list) and search_data["results"]:
            occupation_uri = search_data["results"][0].get("uri") or search_data["results"][0].get("id")
        if not occupation_uri and "_embedded" in search_data:
            for value in search_data["_embedded"].values():
                if isinstance(value, list) and value:
                    occupation_uri = value[0].get("uri") or value[0].get("id")
                    if occupation_uri:
                        break
    if not occupation_uri:
        return []

    detail_url = f"{base}/resource/occupation"
    detail_data = _safe_get(detail_url, headers=headers, params={"uri": occupation_uri, "language": "en"})
    if not detail_data:
        return []

    labels = _extract_labels_from_obj(detail_data)
    cleaned = []
    seen = set()
    for label in labels:
        normalized = re.sub(r"\s+", " ", label).strip()
        if 2 <= len(normalized) <= 80:
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                cleaned.append(normalized)
    return cleaned[:40]


def _ensure_upsc_question_bank():
    if Question.query.filter_by(exam="UPSC").first():
        return
    questions = []
    for topic in UPSC_TEMPLATE_TOPICS:
        questions.append({
            "exam": "UPSC",
            "subject": topic.split(":")[0],
            "topic": topic,
            "question_text": f"Explain the key ideas in {topic} and mention two recent examples.",
            "answer_text": "Answer outline: define terms, list core concepts, add recent example and impact.",
            "difficulty": "medium"
        })
        questions.append({
            "exam": "UPSC",
            "subject": topic.split(":")[0],
            "topic": topic,
            "question_text": f"Write a 150-word note on {topic}.",
            "answer_text": "Answer outline: intro (2-3 lines), body (key points), conclusion (future direction).",
            "difficulty": "medium"
        })
    for item in questions[:240]:
        db.session.add(Question(**item))
    db.session.commit()


def _fetch_opentdb_questions(amount=10, difficulty="medium"):
    params = {"amount": amount, "type": "multiple", "difficulty": difficulty}
    data = _safe_get(OPENTDB_API, params=params)
    if not data or data.get("response_code") != 0:
        return []
    questions = []
    for item in data.get("results", []):
        question = item.get("question")
        correct = item.get("correct_answer")
        incorrect = item.get("incorrect_answers", [])
        options = incorrect + [correct]
        questions.append({
            "question": question,
            "options": options,
            "answer": correct,
            "category": item.get("category")
        })
    return questions


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


def _schedule_items(items, start_date, timeline_weeks, hours_per_week, study_days_per_week, pace_mode="steady"):
    tasks = []
    if not items:
        items = ["Define milestones", "Gather resources", "Start learning", "Build a mini project"]

    estimated_hours = [_estimate_hours(item) for item in items]
    total_hours = sum(estimated_hours) or 1
    pace_mode = _normalize_pace_mode(pace_mode)
    pace_multiplier = {
        "burnout_safe": 1.2,
        "steady": 1.0,
        "sprint": 0.85,
    }[pace_mode]
    if timeline_weeks and timeline_weeks > 0:
        total_days = max(timeline_weeks * 7, 7)
    else:
        total_days = max(math.ceil(total_hours / max(hours_per_week, 1) * 7 * pace_multiplier), 7)

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


def _auto_adjust_roadmap_timeline(roadmap, start_date=None, timeline_weeks=0):
    remaining_tasks = Task.query.filter_by(roadmap_id=roadmap.id).filter(Task.status != "done").order_by(Task.order_index.asc()).all()
    completed_tasks = Task.query.filter_by(roadmap_id=roadmap.id, status="done").order_by(Task.order_index.asc()).all()

    roadmap.completed_tasks = len(completed_tasks)

    completed_hours = 0.0
    for task in completed_tasks:
        completed_hours += task.actual_hours if task.actual_hours and task.actual_hours > 0 else task.estimated_hours or 0.0

    if not remaining_tasks:
        last_completed = max(
            [task.completed_at.date() for task in completed_tasks if task.completed_at],
            default=_utc_today()
        )
        roadmap.target_date = last_completed
        roadmap.total_hours_est = round(completed_hours, 1)
        return

    schedule_start = start_date or _utc_today()
    task_specs, remaining_hours, computed_end = _schedule_items(
        [task.title for task in remaining_tasks],
        schedule_start,
        timeline_weeks,
        roadmap.hours_per_week,
        roadmap.study_days_per_week,
        _extract_pace_mode_from_source_text(roadmap.source_text),
    )

    for task, spec in zip(remaining_tasks, task_specs):
        task.due_date = spec["due_date"]
        task.estimated_hours = spec["estimated_hours"]

    roadmap.target_date = computed_end
    roadmap.total_hours_est = round(completed_hours + remaining_hours, 1)


def _build_recent_updates(roadmap):
    updates = []

    if _has_table("checkin"):
        for checkin in Checkin.query.filter_by(roadmap_id=roadmap.id).order_by(Checkin.created_at.desc()).limit(8).all():
            text_bits = []
            if checkin.minutes:
                text_bits.append(f"{checkin.minutes} minutes logged")
            if checkin.note:
                text_bits.append(checkin.note)
            updates.append({
                "kind": "checkin",
                "title": "Progress update",
                "body": " - ".join(text_bits) if text_bits else "Study session logged",
                "when": checkin.created_at,
            })

    for task in Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.updated_at.desc()).limit(12).all():
        if task.notes or task.status == "done":
            body_parts = []
            if task.status == "done":
                body_parts.append("Marked complete")
            elif task.status == "doing":
                body_parts.append("In progress")
            if task.notes:
                body_parts.append(task.notes)
            updates.append({
                "kind": "task",
                "title": task.title,
                "body": " - ".join(body_parts),
                "when": task.updated_at,
            })

    updates.sort(key=lambda item: item["when"] or datetime.min, reverse=True)
    return updates[:10]


def _build_week_plan(tasks, tests):
    today = _utc_today()
    week_end = today + timedelta(days=7)
    week_tasks = [task for task in tasks if task.status != "done" and task.due_date and today <= task.due_date <= week_end][:5]
    week_tests = [test for test in tests if today <= test.scheduled_date <= week_end][:3]
    return {"tasks": week_tasks, "tests": week_tests}


def _build_plan_quality_report(roadmap, tasks):
    warnings = []
    normalized_titles = [_normalize(task.title) for task in tasks]
    duplicates = len(normalized_titles) - len(set(normalized_titles))
    vague_markers = {"introduction", "overview", "basics", "fundamentals", "misc", "general"}
    vague_tasks = [task for task in tasks if _normalize(task.title) in vague_markers or len(task.title.split()) <= 1]

    by_week = {}
    for task in tasks:
        if not task.due_date:
            continue
        week_key = task.due_date - timedelta(days=task.due_date.weekday())
        by_week.setdefault(week_key, 0)
        by_week[week_key] += 1
    overloaded = max(by_week.values(), default=0)

    hard_streak = 0
    hard_streak_max = 0
    for task in tasks:
        if task.difficulty == "hard":
            hard_streak += 1
            hard_streak_max = max(hard_streak_max, hard_streak)
        else:
            hard_streak = 0

    revision_count = len([task for task in tasks if "revision" in _normalize(task.title)])
    proof_count = len([task for task in tasks if any(marker in _normalize(task.title) for marker in ["project:", "portfolio", "resume", "interview", "case study", "proof"])])

    if duplicates:
        warnings.append({"tone": "high", "title": "Duplicate work detected", "detail": f"{duplicates} duplicated task(s) make the plan feel noisier than it should."})
    if vague_tasks:
        warnings.append({"tone": "medium", "title": "Some tasks are too vague", "detail": "A few tasks may need clearer action words or stronger outcomes."})
    if overloaded >= 6:
        warnings.append({"tone": "high", "title": "One week looks overloaded", "detail": f"At least one week carries {overloaded} tasks. That may hurt consistency."})
    if hard_streak_max >= 3:
        warnings.append({"tone": "medium", "title": "Hard-task cluster", "detail": f"There are {hard_streak_max} hard tasks in sequence. Mix in lighter wins."})
    if revision_count == 0:
        warnings.append({"tone": "high", "title": "Revision blocks are missing", "detail": "The roadmap needs revision loops, not only fresh study."})
    if proof_count == 0 and roadmap.roadmap_type != "syllabus":
        warnings.append({"tone": "medium", "title": "Proof tasks are thin", "detail": "Career and UPSC plans should end in visible proof, not just consumption."})
    if not warnings:
        warnings.append({"tone": "low", "title": "Quality check passed", "detail": "This roadmap has a healthy mix of action, proof, and revision."})
    return warnings


def _build_milestone_timeline(tasks):
    milestones = []
    for task in tasks[:8]:
        milestones.append({
            "title": task.title,
            "when": task.due_date,
            "done": task.status == "done",
        })
    return milestones


def _build_progress_story(roadmap, attempts, quiz_results):
    story = []
    recent_checkins = []
    previous_checkins = []
    if _has_table("checkin"):
        month_start = _utc_now() - timedelta(days=30)
        previous_start = _utc_now() - timedelta(days=60)
        recent_checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).filter(Checkin.created_at >= month_start).all()
        previous_checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).filter(Checkin.created_at >= previous_start, Checkin.created_at < month_start).all()
    if roadmap.streak >= 3:
        story.append("Your consistency streak is starting to become a real system.")
    if recent_checkins:
        recent_minutes = sum(item.minutes or 0 for item in recent_checkins)
        previous_minutes = sum(item.minutes or 0 for item in previous_checkins)
        if recent_minutes > previous_minutes and previous_minutes > 0:
            story.append("Month-over-month study time is improving, which is a strong sign the system is getting more stable.")
        elif recent_minutes >= 240:
            story.append("You are putting in enough logged time for progress to become visible, not just theoretical.")
    if quiz_results and len(quiz_results) >= 2:
        latest = quiz_results[0].correct / max(quiz_results[0].total_questions, 1)
        older = quiz_results[-1].correct / max(quiz_results[-1].total_questions, 1)
        if latest > older:
            story.append("You used to struggle more on quizzes. Accuracy is improving.")
    if attempts:
        scores = [attempt.score for attempt in attempts.values()]
        if scores and max(scores) - min(scores) >= 2:
            story.append("Your answer-writing quality is uneven, which means the next gains will come from consistency.")
    if not story:
        story.append("Progress is still forming. Keep logging work and the story will become visible.")
    return story[:3]


def _build_dashboard_insights(roadmaps):
    if not roadmaps:
        return []
    roadmap_ids = [item.id for item in roadmaps]
    tasks = Task.query.filter(Task.roadmap_id.in_(roadmap_ids)).all()
    checkins = Checkin.query.filter(Checkin.roadmap_id.in_(roadmap_ids)).all() if _has_table("checkin") else []

    best_day = None
    if checkins:
        day_map = {}
        for item in checkins:
            day_name = item.checkin_date.strftime("%A")
            day_map.setdefault(day_name, 0)
            day_map[day_name] += item.minutes or 0
        best_day = max(day_map.items(), key=lambda pair: pair[1])[0]

    strongest_habit = "Showing up consistently" if any(item.minutes and item.minutes >= 30 for item in checkins) else "Building the habit"
    weakest_pattern = "Tasks get delayed when too many hard items stack together." if len([task for task in tasks if task.difficulty == "hard" and task.status != "done"]) >= 3 else "Momentum drops when check-ins disappear."
    delayed = [task for task in tasks if task.status != "done" and task.due_date and task.due_date < _utc_today()]
    delayed_type = delayed[0].difficulty if delayed else "No major delay pattern"
    return [
        {"title": "Strongest habit", "detail": strongest_habit},
        {"title": "Weakest pattern", "detail": weakest_pattern},
        {"title": "Best study day", "detail": best_day or "Not enough history yet"},
        {"title": "Most delayed topic type", "detail": delayed_type},
    ]


def _parse_checkin_signals(note):
    if not note:
        return {}
    signals = {}
    load_match = re.search(r"Load:([^|]+)", note, flags=re.IGNORECASE)
    confidence_match = re.search(r"Confidence:([^|]+)", note, flags=re.IGNORECASE)
    if load_match:
        signals["load"] = load_match.group(1).strip()
    if confidence_match:
        signals["confidence"] = confidence_match.group(1).strip()
    return signals


def _build_weekly_change_summary(roadmap, tasks, tests):
    week_start = _utc_now() - timedelta(days=7)
    completed = [task for task in tasks if task.completed_at and task.completed_at >= week_start]
    checkins = []
    if _has_table("checkin"):
        checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).filter(Checkin.created_at >= week_start).all()
    completed_tests = [test for test in tests if test.status == "completed" and test.created_at and test.created_at >= week_start]
    minutes = sum(item.minutes or 0 for item in checkins)
    return {
        "tasks_completed": len(completed),
        "minutes_logged": minutes,
        "tests_completed": len(completed_tests),
        "message": "Momentum is building." if len(completed) >= 2 or minutes >= 180 else "A small reset this week can quickly restore momentum.",
    }


def _build_monthly_review(roadmap, tasks, tests):
    period_start = _utc_now() - timedelta(days=30)
    completed = [task for task in tasks if task.completed_at and task.completed_at >= period_start]
    active = [task for task in tasks if task.status == "doing"]
    overdue = [task for task in tasks if task.status != "done" and task.due_date and task.due_date < _utc_today()]
    checkins = []
    if _has_table("checkin"):
        checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).filter(Checkin.created_at >= period_start).all()
    total_minutes = sum(item.minutes or 0 for item in checkins)
    return {
        "tasks_completed": len(completed),
        "active_tasks": len(active),
        "minutes_logged": total_minutes,
        "overdue_count": len(overdue),
        "headline": "Strong month of execution." if len(completed) >= 4 else "Your system still has room to tighten.",
        "summary": "You are turning plans into output." if len(completed) >= 4 else "A steadier weekly rhythm will make the roadmap feel much lighter.",
    }


def _build_risk_alerts(roadmap, tasks, tests, forecast):
    alerts = []
    today = _utc_today()
    overdue = [task for task in tasks if task.status != "done" and task.due_date and task.due_date < today]
    due_soon = [task for task in tasks if task.status != "done" and task.due_date and today <= task.due_date <= today + timedelta(days=3)]
    hard_open = [task for task in tasks if task.status != "done" and task.difficulty == "hard"][:3]
    missed_tests = [test for test in tests if test.status == "missed"]

    if forecast and forecast > roadmap.target_date:
        slip_days = max((forecast - roadmap.target_date).days, 1)
        alerts.append({"title": "Deadline risk", "detail": f"At the current pace, you may finish about {slip_days} day(s) late.", "tone": "high"})
    if overdue:
        alerts.append({"title": "Overdue tasks", "detail": f"{len(overdue)} task(s) are overdue and need a catch-up decision.", "tone": "high"})
    if len(due_soon) >= 3:
        alerts.append({"title": "Crowded next 72 hours", "detail": f"{len(due_soon)} items are due soon. Protect a focused block before adding anything new.", "tone": "medium"})
    if missed_tests:
        alerts.append({"title": "Test rhythm slipped", "detail": f"{len(missed_tests)} test(s) were missed. Rebooking one checkpoint will restore confidence.", "tone": "medium"})
    if hard_open:
        alerts.append({"title": "Weak-area cluster", "detail": f"Hard unfinished work is building up around {hard_open[0].title}.", "tone": "medium"})
    if not alerts:
        alerts.append({"title": "Low immediate risk", "detail": "Your roadmap is stable right now. Stay consistent and protect revision time.", "tone": "low"})
    return alerts[:4]


def _build_recovery_options(roadmap, tasks, forecast):
    remaining_tasks = [task for task in tasks if task.status != "done"]
    if not remaining_tasks:
        return [{"title": "Celebrate and extend", "detail": "You finished this roadmap. Archive it, export it, or start the next mission.", "impact": "positive"}]

    today = _utc_today()
    remaining_hours = round(sum(task.estimated_hours or 0 for task in remaining_tasks), 1)
    days_left = max((roadmap.target_date - today).days, 1)
    hours_needed = math.ceil(remaining_hours / max(days_left / 7, 1))
    options = [
        {
            "title": "Hold the current rhythm",
            "detail": f"Stay at {roadmap.hours_per_week} hr/week and keep your next action small enough to finish today.",
            "impact": "steady",
        }
    ]

    if hours_needed > roadmap.hours_per_week:
        options.append({
            "title": "Increase weekly hours",
            "detail": f"Raise your study rhythm to about {hours_needed} hr/week to protect the current deadline.",
            "impact": "urgent",
        })

    if forecast and forecast > roadmap.target_date:
        extend_weeks = max(math.ceil((forecast - roadmap.target_date).days / 7), 1)
        options.append({
            "title": "Extend the timeline",
            "detail": f"Add about {extend_weeks} week(s) if you want to preserve quality and reduce pressure.",
            "impact": "calm",
        })

    options.append({
        "title": "Use burnout-safe catch-up",
        "detail": "Keep one lighter day each week, finish overdue work first, and avoid stacking more than two hard tasks back to back.",
        "impact": "calm",
    })
    return options[:3]


def _build_execution_support(roadmap, tasks, tests):
    today = _utc_today()
    next_task = next((task for task in tasks if task.status != "done"), None)
    if next_task:
        session_minutes = max(25, min(int((next_task.estimated_hours or 1) * 60), 120))
        why_now = "It unlocks the next milestone." if next_task.difficulty != "hard" else "Finishing this hard block will reduce future stress."
    else:
        session_minutes = 30
        why_now = "Use the time for revision, reflection, or your next goal."

    overdue = len([task for task in tasks if task.status != "done" and task.due_date and task.due_date < today])
    return {
        "pace_mode": _pace_label(_extract_pace_mode_from_source_text(roadmap.source_text)),
        "session_minutes": session_minutes,
        "why_now": why_now,
        "deadline_feel": "At risk" if overdue else "Controlled",
        "next_reset": "Catch up on overdue work first." if overdue else "Protect your next focused session.",
        "tests_planned": len([test for test in tests if test.status == "planned"]),
    }


def _build_adaptation_status(roadmap):
    today = _utc_today()
    days_since = None
    if roadmap.last_checkin_date:
        days_since = (today - roadmap.last_checkin_date).days
    recent_checkins = []
    if _has_table("checkin"):
        recent_checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).order_by(Checkin.created_at.desc()).limit(5).all()

    load_markers = []
    confidence_markers = []
    for item in recent_checkins:
        parsed = _parse_checkin_signals(item.note)
        if parsed.get("load"):
            load_markers.append(_normalize(parsed["load"]))
        if parsed.get("confidence"):
            confidence_markers.append(_normalize(parsed["confidence"]))

    heavy_load = len([item for item in load_markers if item in {"heavy", "overloaded", "exhausted"}])
    fragile_confidence = len([item for item in confidence_markers if item in {"low", "fragile", "shaky"}])
    streak_rescue = days_since is not None and days_since >= 3

    if streak_rescue:
        headline = "Streak rescue mode"
        detail = "Momentum slipped for a few days. Restart with one small win today instead of trying to catch up on everything."
    elif heavy_load >= 2 or fragile_confidence >= 2:
        headline = "Burnout-safe adjustment"
        detail = "Recent check-ins suggest the plan feels heavy. Shorter sessions and revision-first work will protect consistency."
    else:
        headline = "System stable"
        detail = "Your current rhythm looks manageable. Keep the next move small and repeatable."

    return {
        "headline": headline,
        "detail": detail,
        "days_since_checkin": days_since,
        "heavy_load": heavy_load,
        "fragile_confidence": fragile_confidence,
        "streak_rescue": streak_rescue,
    }


def _build_confidence_signals(roadmap, tasks):
    project_count = len([task for task in tasks if task.title.startswith("Project:")])
    return [
        {"title": "Editable roadmap origin", "detail": "This plan came through a preview-and-confirm flow instead of locking instantly."},
        {"title": "Adaptive schedule", "detail": "Due dates rebalance as you check in, complete tasks, or change the timeline."},
        {"title": "Execution proof", "detail": f"{roadmap.completed_tasks} task(s) completed and {project_count} outcome-driven project block(s) mapped."},
    ]


def _build_outcome_artifacts(roadmap, tasks):
    project_titles = [task.title.replace("Project: ", "") for task in tasks if task.title.startswith("Project:")]
    if roadmap.roadmap_type == "career":
        artifacts = [
            {"title": "Portfolio proof", "detail": project_titles[0] if project_titles else "Ship one portfolio-ready project from this roadmap."},
            {"title": "Resume bullet", "detail": "Turn completed projects and milestones into measurable resume achievements."},
            {"title": "Interview story", "detail": "Use your hardest completed task as a proof point for problem-solving and consistency."},
        ]
    elif roadmap.roadmap_type == "upsc":
        artifacts = [
            {"title": "Prelims confidence", "detail": "Convert PYQ and quiz progress into stronger accuracy under pressure."},
            {"title": "Mains proof", "detail": "Build answer-writing consistency and mock analysis that improve written performance."},
            {"title": "Revision discipline", "detail": "Use milestone completion and test rhythm as proof that your system is working."},
        ]
    else:
        artifacts = [
            {"title": "Concept mastery", "detail": "Use completion, notes, and revision to prove this syllabus is actually being absorbed."},
            {"title": "Revision readiness", "detail": "A finished roadmap should leave you with clear weak areas and a review plan."},
            {"title": "Visible momentum", "detail": "Every completed block turns the syllabus into something measurable and manageable."},
        ]
    return artifacts


def _build_weak_area_summary(questions, attempts):
    if not questions:
        return []

    question_map = {q.id: q for q in questions}
    topic_buckets = {}
    for question_id, attempt in attempts.items():
        question = question_map.get(question_id)
        if not question:
            continue
        topic = (question.topic or question.subject or "General practice").strip()
        bucket = topic_buckets.setdefault(topic, {"scores": [], "count": 0})
        bucket["scores"].append(attempt.score)
        bucket["count"] += 1

    insights = []
    for topic, payload in topic_buckets.items():
        avg_score = round(sum(payload["scores"]) / max(len(payload["scores"]), 1), 1)
        repeated_misses = len([score for score in payload["scores"] if score <= 2])
        if avg_score < 2.5:
            action = "Relearn the core idea and answer one small question again tomorrow."
            tone = "high"
        elif avg_score < 3.5:
            action = "Keep practicing until your answer structure becomes quicker and cleaner."
            tone = "medium"
        else:
            action = "This area is improving. Protect it with revision instead of over-studying."
            tone = "low"
        insights.append({
            "topic": topic,
            "avg_score": avg_score,
            "attempts": payload["count"],
            "repeated_misses": repeated_misses,
            "quiz_vs_writing": "Writing lag" if avg_score < 3 and payload["count"] >= 2 else "Stable",
            "action": action,
            "tone": tone,
        })

    insights.sort(key=lambda item: (item["avg_score"], -item["attempts"], item["topic"]))
    return insights[:5]


def _build_practice_coach(pyq_total, avg_score, weak_areas):
    if pyq_total < 10:
        headline = "Pattern recognition still needs work."
        recommendation = "Push PYQ coverage before adding too many fresh sources."
    elif avg_score < 3.5:
        headline = "Knowledge is there, but written execution is lagging."
        recommendation = "Focus on timed answer writing and shorter review loops."
    else:
        headline = "Your practice system is getting stronger."
        recommendation = "Increase test pressure gradually instead of dramatically."

    weak_area = weak_areas[0]["topic"] if weak_areas else "General accuracy"
    gap_signal = weak_areas[0]["quiz_vs_writing"] if weak_areas else "Stable"
    return {
        "headline": headline,
        "recommendation": recommendation,
        "focus_topic": weak_area,
        "gap_signal": gap_signal,
    }


def _build_today_focus(roadmap, tasks, tests, weak_areas=None):
    today = _utc_today()
    weak_areas = weak_areas or []
    weak_markers = {_normalize(item.get("topic", "")) for item in weak_areas if item.get("topic")}

    def task_priority(task):
        normalized = _normalize(task.title)
        score = 0
        if task.status == "done":
            score -= 100
        if task.due_date and task.due_date < today:
            score += 80
        elif task.due_date and task.due_date <= today + timedelta(days=2):
            score += 50
        if "revision" in normalized:
            score += 25
        if any(marker and marker in normalized for marker in weak_markers):
            score += 35
        if task.difficulty == "hard":
            score += 10
        if task.status == "doing":
            score += 15
        return score

    open_tasks = [task for task in tasks if task.status != "done"]
    open_tasks.sort(key=task_priority, reverse=True)
    next_task = open_tasks[0] if open_tasks else None
    upcoming_tests = [test for test in tests if test.status != "completed" and test.scheduled_date >= today]
    next_test = upcoming_tests[0] if upcoming_tests else None

    due_soon = [task for task in tasks if task.status != "done" and task.due_date and task.due_date <= today + timedelta(days=3)]
    revision_task = next(
        (task for task in open_tasks if "revision" in _normalize(task.title)),
        next_task,
    )

    return {
        "next_task": next_task,
        "next_test": next_test,
        "revision_task": revision_task,
        "due_soon_count": len(due_soon),
    }


def _build_quiz_next_steps(accuracy, result):
    steps = []
    if accuracy < 50:
        steps.append("Switch to a shorter quiz after revising the weakest topic.")
        steps.append("Do not increase volume yet. Fix accuracy before speed.")
    elif accuracy < 75:
        steps.append("Keep the same difficulty and improve elimination quality.")
        steps.append("Review wrong answers and connect them to one revision session.")
    else:
        steps.append("Raise either difficulty or volume, but not both at the same time.")
        steps.append("Use this score as proof that your revision loop is working.")

    if result.incorrect > result.correct:
        steps.append("Too many risky attempts. Slow down and answer more selectively.")
    elif result.correct == result.total_questions:
        steps.append("Try a harder paper or a longer set to stretch your edge.")
    else:
        steps.append("Retest within 48 hours to lock in retention.")
    return steps[:3]


def _build_resource_groups(resources):
    groups = {
        "Start here": [],
        "Official source": [],
        "Deep study": [],
        "Quick revision": [],
        "Practice-first": [],
    }

    for res in resources:
        provider = ((res.get("provider") if isinstance(res, dict) else res.provider) or "").lower()
        title = _normalize((res.get("title") if isinstance(res, dict) else res.title) or "")
        summary = _normalize((res.get("summary") if isinstance(res, dict) else res.summary) or "")

        tags = (res.get("tags") if isinstance(res, dict) else []) or []
        if "Practice-first" in tags:
            target = "Practice-first"
        elif provider in {"upsc", "official", "ncert"}:
            target = "Official source"
        elif any(marker in title or marker in summary for marker in ["summary", "outline", "quick", "revision", "notes"]):
            target = "Quick revision"
        elif provider in {"crossref", "research"} or any(marker in title for marker in ["analysis", "advanced", "deep"]):
            target = "Deep study"
        else:
            target = "Start here"
        groups[target].append(res)

    ordered = []
    for label in ["Start here", "Official source", "Deep study", "Quick revision", "Practice-first"]:
        if groups[label]:
            ordered.append({"label": label, "resources": groups[label][:3]})
    return ordered


def _resource_topic_markers(task_title, optional_subject=""):
    title = _normalize(task_title)
    markers = set()

    mapping = {
        "strategy": ["strategy", "planning", "foundation", "attempt", "timeline"],
        "foundation": ["ncert", "foundation", "basic", "build-up"],
        "current affairs": ["current affairs", "news", "notes"],
        "polity": ["polity", "constitution", "parliament", "judiciary", "federalism", "governance"],
        "history": ["history", "freedom struggle", "heritage", "culture", "world history"],
        "geography": ["geography", "physical", "human"],
        "economy": ["economy", "budget", "banking", "agriculture"],
        "environment": ["environment", "ecology", "biodiversity"],
        "science": ["science", "technology", "space"],
        "international relations": ["international relations", "foreign policy"],
        "social justice": ["social justice", "society", "welfare"],
        "ethics": ["ethics", "integrity", "case study"],
        "essay": ["essay"],
        "csat": ["csat", "reasoning", "numeracy", "comprehension", "aptitude"],
        "pyq": ["pyq", "previous year"],
        "answer writing": ["answer writing", "time-bound answer", "mains enrichment"],
        "interview": ["interview", "daf", "panel", "communication", "personality"],
        "mains": ["mains", "general studies"],
        "prelims": ["prelims"],
        "revision": ["revision", "mock", "test"],
        "optional": ["optional subject"],
    }

    for topic_key, keywords in mapping.items():
        if any(keyword in title for keyword in keywords):
            markers.add(topic_key)

    if optional_subject and "optional subject" in title:
        markers.add("optional")
    if not markers:
        markers.update({"strategy", "foundation"})
    return markers


def _subject_pack_keys_for_task(task_markers):
    keys = []
    if {"strategy", "foundation"} & task_markers:
        keys.append("foundation")
    if {"prelims", "polity", "history", "geography", "economy", "environment", "science", "pyq"} & task_markers:
        keys.append("prelims_gs")
    if "csat" in task_markers:
        keys.append("csat")
    if "essay" in task_markers:
        keys.append("essay")
    if {"history", "geography", "society"} & task_markers:
        keys.append("gs1")
    if {"polity", "governance", "international relations", "social justice"} & task_markers:
        keys.append("gs2")
    if {"economy", "environment", "science", "technology"} & task_markers:
        keys.append("gs3")
    if "ethics" in task_markers:
        keys.append("gs4")
    if {"answer writing", "mains"} & task_markers:
        keys.append("answer_writing")
    if "interview" in task_markers:
        keys.append("interview")
    if "optional" in task_markers:
        keys.append("optional")

    unique = []
    seen = set()
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _score_curated_resource(task_markers, resource):
    resource_topics = set(resource.get("topics", []))
    overlap = len(task_markers & resource_topics)
    base = 0
    if resource.get("bucket") == "Official source":
        base += 40
    elif resource.get("bucket") == "Start here":
        base += 30
    elif resource.get("bucket") == "Deep study":
        base += 20
    else:
        base += 15
    if "Must use" in resource.get("tags", []):
        base += 15
    if "Official" in resource.get("tags", []):
        base += 10
    return base + (overlap * 18)


def _curated_upsc_resources_for_task(task_title, optional_subject=""):
    task_markers = _resource_topic_markers(task_title, optional_subject)
    pack_keys = _subject_pack_keys_for_task(task_markers)

    selected = []
    seen_urls = set()

    for pack_key in pack_keys:
        pack = UPSC_HAND_TUNED_PACKS.get(pack_key)
        if not pack:
            continue
        for item in pack["resources"]:
            entry = dict(item)
            entry["tags"] = list(dict.fromkeys(entry.get("tags", []) + [pack["label"]]))
            if entry["url"] not in seen_urls:
                selected.append(entry)
                seen_urls.add(entry["url"])

    ranked = sorted(
        UPSC_CURATED_RESOURCES,
        key=lambda item: _score_curated_resource(task_markers, item),
        reverse=True
    )

    for item in ranked:
        if item["url"] in seen_urls:
            continue
        if len(selected) >= 8:
            break
        selected.append(item)
        seen_urls.add(item["url"])

    if optional_subject and any(marker in task_markers for marker in {"optional", "mains"}):
        selected.append({
            "title": f"Optional subject syllabus anchor: {optional_subject}",
            "url": "https://upsc.gov.in/examinations/revised-syllabus-scheme",
            "provider": "upsc",
            "bucket": "Official source",
            "tags": ["Optional", "Official"],
            "use_case": f"Use this as the official syllabus anchor before collecting books or notes for {optional_subject}.",
            "topics": ["optional", "mains"],
        })

    unique = []
    seen = set()
    for item in selected:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique


def _annotate_resource(resource):
    curated_match = next((item for item in UPSC_CURATED_RESOURCES if item["url"] == resource.url or item["title"] == resource.title), None)
    bucket = "Start here"
    tags = ["Useful"]
    use_case = resource.summary or "Open this resource and pull out notes, examples, and revisions relevant to the task."

    if curated_match:
        bucket = curated_match.get("bucket", bucket)
        tags = curated_match.get("tags", tags)
        use_case = curated_match.get("use_case", use_case)
    else:
        provider = (resource.provider or "").lower()
        if provider in {"upsc", "official", "ncert"}:
            bucket = "Official source"
            tags = ["Official"]
        elif provider in {"research", "crossref"}:
            bucket = "Deep study"
            tags = ["Deep study"]
        elif "summary" in _normalize(resource.summary or ""):
            bucket = "Quick revision"
            tags = ["Revision"]

    normalized_title = _normalize(resource.title or "")
    normalized_summary = _normalize(resource.summary or "")
    enhanced_tags = list(tags)
    if bucket == "Official source" and "Official-only" not in enhanced_tags:
        enhanced_tags.append("Official-only")
    if bucket == "Quick revision" and "Fast revision" not in enhanced_tags:
        enhanced_tags.append("Fast revision")
    if bucket == "Deep study" and "Deep study" not in enhanced_tags:
        enhanced_tags.append("Deep study")
    if any(marker in normalized_title or marker in normalized_summary for marker in ["practice", "pyq", "question", "mock"]):
        if "Practice-first" not in enhanced_tags:
            enhanced_tags.append("Practice-first")
    if not any(marker in normalized_title or marker in normalized_summary for marker in ["advanced", "research", "deep"]):
        if "Beginner-friendly" not in enhanced_tags and bucket in {"Start here", "Official source"}:
            enhanced_tags.append("Beginner-friendly")

    return {
        "id": resource.id,
        "provider": resource.provider,
        "title": resource.title,
        "url": resource.url,
        "summary": resource.summary,
        "rating_avg": resource.rating_avg,
        "rating_count": resource.rating_count,
        "flagged_count": resource.flagged_count,
        "bucket": bucket,
        "tags": enhanced_tags,
        "use_case": use_case,
    }


def _resource_use_case(resource, group_label):
    if group_label == "Official source":
        return "Best for syllabus accuracy, PYQs, and exam rules."
    if group_label == "Deep study":
        return "Best when you want deeper conceptual understanding and examples."
    if group_label == "Quick revision":
        return "Best for fast recap before revision or tests."
    return "Best starting point if you are learning this block for the first time."


def _build_milestones(roadmap, tasks, tests, done_map=None, attempts=None):
    total_tasks = len(tasks) or 1
    done_tasks = len([task for task in tasks if task.status == "done"])
    milestones = [
        {
            "title": "First step completed",
            "done": done_tasks >= 1,
            "detail": "Builds early momentum.",
        },
        {
            "title": "25% plan completed",
            "done": done_tasks / total_tasks >= 0.25,
            "detail": f"{done_tasks}/{len(tasks)} tasks finished.",
        },
        {
            "title": "Halfway milestone",
            "done": done_tasks / total_tasks >= 0.5,
            "detail": "A strong sign your system is working.",
        },
        {
            "title": "Mock test rhythm started",
            "done": len([test for test in tests if test.status == "completed"]) >= 1,
            "detail": "Completed tests improve exam readiness.",
        },
    ]

    if roadmap.roadmap_type == "upsc":
        pyq_count = sum(len(years) for years in (done_map or {}).values())
        avg_attempt = 0.0
        if attempts:
            avg_attempt = round(sum(attempt.score for attempt in attempts.values()) / max(len(attempts), 1), 1)
        milestones.extend([
            {
                "title": "PYQ habit building",
                "done": pyq_count >= 5,
                "detail": f"{pyq_count} PYQ years marked complete.",
            },
            {
                "title": "Answer writing consistency",
                "done": avg_attempt >= 3.5 and len(attempts or {}) >= 5,
                "detail": f"Average self-score: {avg_attempt}/5.",
            },
        ])
    return milestones


def _extract_optional_subject_from_source_text(source_text):
    match = re.search(r"Optional Subject:\s*(.+)", source_text or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()


def _build_readiness_metrics(roadmap, tasks, tests, done_map=None, attempts=None, quiz_results=None):
    total_tasks = len(tasks) or 1
    done_ratio = len([task for task in tasks if task.status == "done"]) / total_tasks
    completed_tests = [test for test in tests if test.status == "completed"]
    test_ratio = len(completed_tests) / max(len(tests), 1)
    pyq_total = sum(len(years) for years in (done_map or {}).values())
    pyq_ratio = min(pyq_total / 10, 1.0)
    answer_ratio = 0.0
    if attempts:
        answer_ratio = min((sum(attempt.score for attempt in attempts.values()) / (5 * max(len(attempts), 1))), 1.0)
    quiz_ratio = 0.0
    if quiz_results:
        avg_accuracy = sum((result.correct / max(result.total_questions, 1)) for result in quiz_results) / len(quiz_results)
        quiz_ratio = min(avg_accuracy, 1.0)

    if roadmap.roadmap_type == "upsc":
        prelims = round((done_ratio * 0.3 + test_ratio * 0.3 + pyq_ratio * 0.25 + quiz_ratio * 0.15) * 100)
        mains = round((done_ratio * 0.35 + answer_ratio * 0.35 + test_ratio * 0.2 + pyq_ratio * 0.1) * 100)
        interview = round((done_ratio * 0.4 + test_ratio * 0.2 + answer_ratio * 0.2 + quiz_ratio * 0.2) * 100)
        return [
            {"label": "Prelims readiness", "value": prelims, "hint": "Built from tasks, PYQs, tests, and quiz accuracy."},
            {"label": "Mains readiness", "value": mains, "hint": "Built from answer writing, test work, and study progress."},
            {"label": "Interview readiness", "value": interview, "hint": "Built from consistency and communication-oriented preparation."},
        ]
    overall = round((done_ratio * 0.6 + test_ratio * 0.25 + answer_ratio * 0.15) * 100)
    return [{"label": "Plan readiness", "value": overall, "hint": "Built from task completion, tests, and progress quality."}]


def _build_tasks(roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week, study_days_per_week, pace_mode="steady", source_text=""):
    profile = _extract_profile_from_source_text(source_text)
    workflow_mode = _normalize(profile.get("workflow_mode", "normal"))
    weak_areas = [item.strip() for item in profile.get("weak_areas", "").split(",") if item.strip()]

    all_items = topics[:]
    enriched = []
    for idx, item in enumerate(all_items, start=1):
        enriched.append(item)
        if idx % 3 == 0:
            enriched.append(f"Revision Sprint: {item}")
    all_items = enriched

    if weak_areas:
        for weak in weak_areas[:3]:
            all_items.append(f"Weak-area recovery: {weak}")

    if workflow_mode in {"deadline", "exam"}:
        all_items.append("High-yield revision drill")
        all_items.append("Time-boxed self-test and review")

    if roadmap_type in {"career", "upsc"}:
        for project in projects:
            all_items.append(f"Project: {project}")

    if roadmap_type == "career":
        all_items.extend([
            "Portfolio readiness review",
            "Resume bullet drafting",
            "Interview question bank",
            "Job-ready proof artifact",
        ])
    if roadmap_type == "upsc":
        all_items.extend([
            "Answer writing review framework",
            "Revision calendar before mocks",
            "Issue-based current affairs mapping",
        ])

    return _schedule_items(all_items, start_date, timeline_weeks, hours_per_week, study_days_per_week, pace_mode)


def _background_fetch_resources(app, roadmap_id):
    with app.app_context():
        if not current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
            return
        roadmap = db.session.get(Roadmap, roadmap_id)
        if not roadmap:
            return
        try:
            roadmap.resource_fetch_status = "running"
            roadmap.resource_fetch_started_at = _utc_now().replace(tzinfo=None)
            db.session.commit()
            tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
            for task in tasks:
                if task.resources:
                    continue
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
                task.last_resource_refresh = _utc_now().replace(tzinfo=None)
            roadmap.resource_fetch_status = "done"
            roadmap.resource_fetch_completed_at = _utc_now().replace(tzinfo=None)
            db.session.commit()
        except Exception:
            roadmap.resource_fetch_status = "failed"
            db.session.commit()
        finally:
            db.session.remove()


def _calculate_forecast(roadmap):
    if roadmap.total_tasks == 0:
        return None
    days_elapsed = max((_utc_today() - roadmap.start_date).days, 1)
    pace = roadmap.completed_tasks / days_elapsed
    if pace <= 0:
        return None
    remaining = roadmap.total_tasks - roadmap.completed_tasks
    est_days_left = math.ceil(remaining / pace)
    return _utc_today() + timedelta(days=est_days_left)


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
    demo_cards = [
        {"title": "UPSC 6-month mission", "detail": "Prelims, mains, revision, PYQ, and mock structure in one system."},
        {"title": "Frontend career launch", "detail": "Skills, portfolio proof, resume bullets, and interview prep checkpoints."},
        {"title": "Semester syllabus planner", "detail": "Turn a noisy syllabus into a calm weekly execution plan."},
    ]
    return render_template('home.html', demo_cards=demo_cards)


@dashboard_bp.route('/demo')
def demo():
    demo_plan = {
        "title": "Frontend Developer Launch Demo",
        "summary": "A sample roadmap that turns skill learning into portfolio proof and interview readiness.",
        "today": "Build the first responsive section of a portfolio homepage.",
        "week": ["HTML fundamentals", "CSS layout system", "Responsive portfolio section", "Revision Sprint: HTML fundamentals"],
        "outcomes": ["Portfolio proof", "Resume bullet", "Interview story"],
    }
    return render_template("demo.html", demo_plan=demo_plan)


@dashboard_bp.route('/dashboard')
@login_required
def dashboard():
    user = db.session.get(User, session['user_id'])
    roadmaps = Roadmap.query.filter_by(user_id=user.id).order_by(Roadmap.created_at.desc()).all()
    active_roadmap = roadmaps[0] if roadmaps else None
    active_next = None
    if active_roadmap:
        active_next = Task.query.filter_by(roadmap_id=active_roadmap.id).filter(Task.status != "done").order_by(Task.order_index.asc()).first()
    dashboard_insights = _build_dashboard_insights(roadmaps)
    return render_template('dashboard.html', user=user, roadmaps=roadmaps, active_roadmap=active_roadmap, active_next=active_next, recent_improvements=RECENT_IMPROVEMENTS, dashboard_insights=dashboard_insights)


@dashboard_bp.route('/roadmap/new', methods=['GET', 'POST'])
@login_required
def create_roadmap():
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip()
            roadmap_type = request.form.get('roadmap_type', 'syllabus')
            pace_mode = _normalize_pace_mode(request.form.get('pace_mode', 'steady'))
            current_level = request.form.get('current_level', 'beginner').strip()
            deadline_pressure = request.form.get('deadline_pressure', 'moderate').strip()
            confidence_level = request.form.get('confidence_level', 'growing').strip()
            weak_areas_input = request.form.get('weak_areas', '').strip()
            workflow_mode = request.form.get('workflow_mode', 'normal').strip()
            target_outcome = request.form.get('target_outcome', '').strip()
            if roadmap_type not in {"syllabus", "career"}:
                roadmap_type = "syllabus"
            timeline_weeks = _safe_int(request.form.get('timeline_weeks', 0) or 0, 0, 0, 52)
            hours_per_week = _safe_int(request.form.get('hours_per_week', 6) or 6, 6, 1, 40)
            study_days_per_week = _safe_int(request.form.get('study_days_per_week', 5) or 5, 5, 1, 7)
            start_date = _safe_date(request.form.get('start_date'))

            raw_text = request.form.get('source_text', '').strip()
            confirmed_topics = request.form.get('confirmed_topics', '').strip()
            uploaded = request.files.get('syllabus_file')
            if uploaded and uploaded.filename:
                if not _allowed_file(uploaded.filename, {"pdf", "txt", "docx", "png", "jpg", "jpeg", "bmp", "tiff"}):
                    flash("Unsupported file type. Upload PDF, TXT, DOCX, or image files.")
                    return redirect(url_for('dashboard.create_roadmap'))
                filename = secure_filename(uploaded.filename)
                unique_name = f"{int(_utc_now().timestamp())}_{filename}"
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
            if confirmed_topics:
                topics = [t.strip() for t in confirmed_topics.splitlines() if t.strip()]
            elif roadmap_type == "career":
                key = _normalize(title)
                match = None
                for template_key in CAREER_TEMPLATES.keys():
                    if template_key in key:
                        match = CAREER_TEMPLATES[template_key]
                        break
                if "upsc" in key:
                    topics = UPSC_TEMPLATE_TOPICS
                    projects = [
                        "PYQ drill: last 10 years (set weekly targets)",
                        "Mock test sprint every 2 weeks",
                        "Optional subject deep dive"
                    ]
                    _ensure_upsc_question_bank()
                else:
                    esco_topics = _fetch_career_template_esco(title)
                    if esco_topics:
                        topics = esco_topics
                        projects = [
                            f"Build a {title} portfolio",
                            f"{title} case study with real data",
                            f"Showcase project: {title} mini product"
                        ]
                    elif match:
                        topics = match["topics"]
                        projects = match["projects"]
                    else:
                        topics = _extract_topics_from_text(raw_text)
            else:
                topics = _extract_topics_from_text(raw_text)

            if roadmap_type != "upsc" and (use_ai or current_app.config.get("AI_TOPIC_EXTRACTION_ENABLED")) and raw_text and not confirmed_topics:
                ai_topics = _ai_extract_topics(raw_text)
                if ai_topics:
                    topics = ai_topics

            if roadmap_type == "syllabus" and not confirmed_topics:
                if not topics:
                    flash("Please provide a syllabus text or upload a file with clear topics.")
                    return redirect(url_for('dashboard.create_roadmap'))
                return render_template(
                    "roadmap_preview.html",
                    title=title,
                    roadmap_type=roadmap_type,
                    timeline_weeks=timeline_weeks,
                    hours_per_week=hours_per_week,
                    study_days_per_week=study_days_per_week,
                    pace_mode=pace_mode,
                    current_level=current_level,
                    deadline_pressure=deadline_pressure,
                    confidence_level=confidence_level,
                    weak_areas=weak_areas_input,
                    workflow_mode=workflow_mode,
                    target_outcome=target_outcome,
                    start_date=start_date,
                    raw_text=raw_text,
                    topics="\n".join(topics),
                    original_topics=topics
                )

            if not title:
                title = "Dream Roadmap"
            if not topics and roadmap_type == "syllabus":
                flash("Please provide a syllabus text or upload a file with topics.")
                return redirect(url_for('dashboard.create_roadmap'))

            raw_text = _embed_plan_preferences(raw_text, pace_mode)
            raw_text = _append_metadata_line(raw_text, "Current Level", current_level)
            raw_text = _append_metadata_line(raw_text, "Deadline Pressure", deadline_pressure)
            raw_text = _append_metadata_line(raw_text, "Confidence Level", confidence_level)
            raw_text = _append_metadata_line(raw_text, "Weak Areas", weak_areas_input)
            raw_text = _append_metadata_line(raw_text, "Workflow Mode", workflow_mode)
            raw_text = _append_metadata_line(raw_text, "Target Outcome", target_outcome)
            roadmap, task_ids, auto_fetch, _ = _persist_roadmap(
                roadmap_type, title, raw_text, topics, projects, start_date, timeline_weeks,
                hours_per_week, study_days_per_week, pace_mode=pace_mode
            )
            if auto_fetch:
                thread = threading.Thread(
                    target=_background_fetch_resources,
                    args=(current_app._get_current_object(), roadmap.id),
                    daemon=True
                )
                thread.start()
            flash("Roadmap generated successfully.")
            return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to create roadmap")
            flash("We couldn't generate that roadmap right now. Please try again with cleaner input.")
            return redirect(url_for('dashboard.create_roadmap'))

    return render_template('roadmap_new.html')


@dashboard_bp.route('/upsc/new', methods=['GET', 'POST'])
@login_required
def create_upsc_roadmap():
    if request.method == 'POST':
        try:
            title = request.form.get('title', '').strip() or "UPSC Mission"
            pace_mode = _normalize_pace_mode(request.form.get('pace_mode', 'steady'))
            current_level = request.form.get('current_level', 'aspirant').strip()
            deadline_pressure = request.form.get('deadline_pressure', 'high').strip()
            confidence_level = request.form.get('confidence_level', 'growing').strip()
            weak_areas_input = request.form.get('weak_areas', '').strip()
            workflow_mode = request.form.get('workflow_mode', 'exam').strip()
            target_outcome = request.form.get('target_outcome', 'Clear the next stage with confidence').strip()
            timeline_weeks = _safe_int(request.form.get('timeline_weeks', 0) or 0, 0, 0, 52)
            hours_per_week = _safe_int(request.form.get('hours_per_week', 6) or 6, 6, 1, 40)
            study_days_per_week = _safe_int(request.form.get('study_days_per_week', 5) or 5, 5, 1, 7)
            upsc_focus = request.form.get('upsc_focus', 'full_journey').strip() or "full_journey"
            if upsc_focus not in UPSC_DEFAULT_SUBJECTS_BY_FOCUS:
                upsc_focus = "full_journey"
            upsc_optional_subject = request.form.get('upsc_optional_subject', '').strip()
            upsc_subjects = request.form.getlist('upsc_subjects')
            if not upsc_subjects:
                serialized_subjects = request.form.get('selected_upsc_subjects', '').strip()
                if serialized_subjects:
                    upsc_subjects = [item.strip() for item in serialized_subjects.split(",") if item.strip()]
            start_date = _safe_date(request.form.get('start_date'))
            personalization_notes = request.form.get('source_text', '').strip()
            confirmed_topics = request.form.get('confirmed_topics', '').strip()
            _, projects, upsc_subjects = _build_upsc_subject_plan(upsc_subjects, upsc_optional_subject, upsc_focus)
            raw_text = _embed_plan_preferences(
                _compose_upsc_source_text(upsc_subjects, upsc_optional_subject, upsc_focus, personalization_notes),
                pace_mode
            )
            raw_text = _append_metadata_line(raw_text, "Current Level", current_level)
            raw_text = _append_metadata_line(raw_text, "Deadline Pressure", deadline_pressure)
            raw_text = _append_metadata_line(raw_text, "Confidence Level", confidence_level)
            raw_text = _append_metadata_line(raw_text, "Weak Areas", weak_areas_input)
            raw_text = _append_metadata_line(raw_text, "Workflow Mode", workflow_mode)
            raw_text = _append_metadata_line(raw_text, "Target Outcome", target_outcome)

            if confirmed_topics:
                topics = [t.strip() for t in confirmed_topics.splitlines() if t.strip()]
                if not topics:
                    flash("Please keep at least one study block in your UPSC plan.")
                    return redirect(url_for('dashboard.create_upsc_roadmap'))
            else:
                topics, projects, upsc_subjects = _build_upsc_subject_plan(upsc_subjects, upsc_optional_subject, upsc_focus)
                _ensure_upsc_question_bank()

            if not confirmed_topics:
                return render_template(
                    "roadmap_preview.html",
                    title=title,
                    roadmap_type="upsc",
                    timeline_weeks=timeline_weeks,
                    hours_per_week=hours_per_week,
                    study_days_per_week=study_days_per_week,
                    pace_mode=pace_mode,
                    current_level=current_level,
                    deadline_pressure=deadline_pressure,
                    confidence_level=confidence_level,
                    weak_areas=weak_areas_input,
                    workflow_mode=workflow_mode,
                    target_outcome=target_outcome,
                    start_date=start_date,
                    raw_text=raw_text,
                    upsc_focus=upsc_focus,
                    upsc_optional_subject=upsc_optional_subject,
                    selected_upsc_subjects=",".join(upsc_subjects),
                    topics="\n".join(topics),
                    original_topics=topics
                )

            roadmap, task_ids, auto_fetch, target_date = _persist_roadmap(
                "upsc", title, raw_text, topics, projects, start_date, timeline_weeks,
                hours_per_week, study_days_per_week, upsc_focus, upsc_optional_subject, pace_mode
            )

            if task_ids:
                upsc_tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
                for task in upsc_tasks:
                    for res in _upsc_resources_for_task(task.title, upsc_optional_subject):
                        db.session.add(Resource(
                            provider=res["provider"],
                            title=res["title"],
                            url=res["url"],
                            summary=res.get("use_case", "Curated UPSC resource"),
                            score=0.95,
                            task_id=task.id
                        ))
                if _has_table("mock_test_schedule"):
                    for spec in _build_upsc_test_plan(start_date, target_date, upsc_focus):
                        db.session.add(MockTestSchedule(
                            title=spec["title"],
                            test_type=spec["test_type"],
                            scheduled_date=spec["scheduled_date"],
                            duration_minutes=spec["duration_minutes"],
                            questions_count=spec["questions_count"],
                            roadmap_id=roadmap.id
                        ))
                else:
                    flash("Roadmap created, but mock-test scheduling is unavailable until the database schema is updated.")
                db.session.commit()

            if auto_fetch:
                thread = threading.Thread(
                    target=_background_fetch_resources,
                    args=(current_app._get_current_object(), roadmap.id),
                    daemon=True
                )
                thread.start()
            flash("UPSC Mission generated successfully.")
            return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to create UPSC roadmap")
            flash("UPSC Mission couldn't be generated right now. Please retry in a moment.")
            return redirect(url_for('dashboard.create_upsc_roadmap'))

    return render_template('upsc_new.html')


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
    annotated_resources_map = {}
    for task in tasks:
        resources_map[task.id] = sorted(
            task.resources,
            key=lambda r: (-(r.rating_avg + r.score), r.flagged_count)
        )
        annotated_resources_map[task.id] = [_annotate_resource(item) for item in resources_map[task.id]]
    tests = []
    if _has_table("mock_test_schedule"):
        tests = MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).order_by(MockTestSchedule.scheduled_date.asc()).all()
    upsc_buckets = _build_upsc_dashboard_data(tasks, tests) if roadmap.roadmap_type == "upsc" else []
    recent_updates = _build_recent_updates(roadmap)
    done_map = {}
    attempts = {}
    quiz_results = []
    if roadmap.roadmap_type == "upsc":
        if _has_table("pyq_completion"):
            for c in PyqCompletion.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).all():
                done_map.setdefault(c.exam, []).append(c.year)
        if _has_table("question_attempt"):
            attempts = {a.question_id: a for a in QuestionAttempt.query.filter_by(user_id=session['user_id']).all()}
        if _has_table("quiz_result"):
            quiz_results = QuizResult.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).order_by(QuizResult.attempted_at.desc()).limit(5).all()
    weak_areas = _build_weak_area_summary(Question.query.filter_by(exam="UPSC").limit(60).all() if roadmap.roadmap_type == "upsc" and _has_table("question") else [], attempts)
    today_focus = _build_today_focus(roadmap, tasks, tests, weak_areas)
    week_plan = _build_week_plan(tasks, tests)
    week_changes = _build_weekly_change_summary(roadmap, tasks, tests)
    execution_support = _build_execution_support(roadmap, tasks, tests)
    risk_alerts = _build_risk_alerts(roadmap, tasks, tests, forecast)
    recovery_options = _build_recovery_options(roadmap, tasks, forecast)
    monthly_review = _build_monthly_review(roadmap, tasks, tests)
    adaptation_status = _build_adaptation_status(roadmap)
    confidence_signals = _build_confidence_signals(roadmap, tasks)
    outcome_artifacts = _build_outcome_artifacts(roadmap, tasks)
    quality_report = _build_plan_quality_report(roadmap, tasks)
    milestone_timeline = _build_milestone_timeline(tasks)
    progress_story = _build_progress_story(roadmap, attempts, quiz_results)
    resource_groups_map = {task.id: _build_resource_groups(annotated_resources_map.get(task.id, [])) for task in tasks}
    milestones = _build_milestones(roadmap, tasks, tests, done_map, attempts)
    readiness_metrics = _build_readiness_metrics(roadmap, tasks, tests, done_map, attempts, quiz_results)
    return render_template(
        'roadmap_view.html',
        roadmap=roadmap,
        tasks=tasks,
        progress=progress,
        forecast=forecast,
        last_checkin=last_checkin,
        resources_map=resources_map,
        annotated_resources_map=annotated_resources_map,
        resource_groups_map=resource_groups_map,
        tests=tests,
        upsc_buckets=upsc_buckets,
        recent_updates=recent_updates,
        today_focus=today_focus,
        week_plan=week_plan,
        week_changes=week_changes,
        execution_support=execution_support,
        risk_alerts=risk_alerts,
        recovery_options=recovery_options,
        monthly_review=monthly_review,
        adaptation_status=adaptation_status,
        confidence_signals=confidence_signals,
        outcome_artifacts=outcome_artifacts,
        quality_report=quality_report,
        milestone_timeline=milestone_timeline,
        progress_story=progress_story,
        milestones=milestones,
        readiness_metrics=readiness_metrics
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
    if task.completion_type not in ["planned", "alternative", "revised", "practiced", "solved", "wrote_answers", "built_project", "reviewed_mistakes"]:
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
        unique_name = f"{int(_utc_now().timestamp())}_{filename}"
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
        task.completed_at = _utc_now().replace(tzinfo=None)
    elif new_status != "done":
        task.completed_at = None

    _auto_adjust_roadmap_timeline(roadmap)
    db.session.commit()
    if new_status == "done":
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id, celebrate=1, _anchor=f"task-{task.id}"))
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/practice', methods=['GET', 'POST'])
@login_required
def practice(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if not all(_has_table(name) for name in ["question", "question_attempt", "pyq_completion"]):
        flash("Practice Vault is temporarily unavailable until the database schema is updated.")
        return redirect(url_for('dashboard.dashboard'))
    _ensure_upsc_question_bank()
    questions = Question.query.filter_by(exam="UPSC").limit(60).all()
    attempts = {a.question_id: a for a in QuestionAttempt.query.filter_by(user_id=session['user_id']).all()}
    current_year = _utc_now().year
    years = list(range(current_year - 9, current_year + 1))
    completions = PyqCompletion.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).all()
    done_map = {}
    for c in completions:
        done_map.setdefault(c.exam, []).append(c.year)
    pyq_total = sum(len(items) for items in done_map.values())
    avg_score = round(sum(a.score for a in attempts.values()) / max(len(attempts), 1), 1) if attempts else 0.0
    weak_areas = _build_weak_area_summary(questions, attempts)
    practice_coach = _build_practice_coach(pyq_total, avg_score, weak_areas)
    readiness_metrics = _build_readiness_metrics(
        roadmap,
        Task.query.filter_by(roadmap_id=roadmap.id).all(),
        MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).all() if _has_table("mock_test_schedule") else [],
        done_map,
        attempts,
        QuizResult.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).order_by(QuizResult.attempted_at.desc()).limit(5).all() if _has_table("quiz_result") else []
    )
    return render_template(
        "practice.html",
        roadmap=roadmap,
        questions=questions,
        attempts=attempts,
        years=years,
        exams=UPSC_EXAMS,
        done_map=done_map,
        pyq_total=pyq_total,
        avg_score=avg_score,
        weak_areas=weak_areas,
        practice_coach=practice_coach,
        readiness_metrics=readiness_metrics
    )


@dashboard_bp.route('/roadmap/<int:roadmap_id>/quiz', methods=['GET'])
@login_required
def quiz(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if not _has_table("quiz_result"):
        flash("Quiz history is temporarily unavailable until the database schema is updated.")
        return redirect(url_for('dashboard.dashboard'))
    amount = _safe_int(request.args.get("amount", 10), 10, 5, 20)
    difficulty = request.args.get("difficulty", "medium")
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"
    questions = _fetch_opentdb_questions(amount=amount, difficulty=difficulty)
    if not questions:
        flash("Quiz generator is busy. Try again in a minute.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
    recent_results = QuizResult.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).order_by(QuizResult.attempted_at.desc()).limit(5).all()
    return render_template("quiz.html", roadmap=roadmap, questions=questions, recent_results=recent_results, selected_amount=amount, selected_difficulty=difficulty)


@dashboard_bp.route('/roadmap/<int:roadmap_id>/quiz/submit', methods=['POST'])
@login_required
def quiz_submit(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    total = int(request.form.get("total", 0))
    correct = 0
    incorrect = 0
    for idx in range(total):
        selected = request.form.get(f"q_{idx}")
        answer = request.form.get(f"a_{idx}")
        if not selected:
            continue
        if selected == answer:
            correct += 1
        else:
            incorrect += 1
    score = (correct * 2) - (incorrect * (2 / 3))
    accuracy = round((correct / max(total, 1)) * 100, 2)
    result = QuizResult(
        total_questions=total,
        correct=correct,
        incorrect=incorrect,
        score=round(score, 2),
        user_id=session['user_id'],
        roadmap_id=roadmap.id
    )
    db.session.add(result)
    db.session.commit()
    analysis = []
    if accuracy >= 75:
        analysis.append("Strong quiz performance. Keep test rhythm steady and keep revising weak pockets.")
    elif accuracy >= 50:
        analysis.append("Moderate performance. Revision and more PYQ-based testing will improve accuracy.")
    else:
        analysis.append("This score suggests you should slow down, revise, and retest after consolidating basics.")
    if incorrect > correct:
        analysis.append("Too many risky attempts. Work on elimination and selective answering.")
    if correct < max(total // 2, 4):
        analysis.append("Focus on concept revision before the next test instead of adding too many new topics.")
    next_steps = _build_quiz_next_steps(accuracy, result)
    return render_template("quiz_result.html", roadmap=roadmap, result=result, accuracy=accuracy, analysis=analysis, next_steps=next_steps)


@dashboard_bp.route('/roadmap/<int:roadmap_id>/pyq', methods=['POST'])
@login_required
def pyq_tracker(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    exam = request.form.get("exam", "UPSC")
    selected_years = request.form.getlist("years")
    PyqCompletion.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id, exam=exam).delete()
    for year_str in selected_years:
        try:
            year = int(year_str)
        except ValueError:
            continue
        db.session.add(PyqCompletion(
            exam=exam,
            year=year,
            user_id=session['user_id'],
            roadmap_id=roadmap.id
        ))
    db.session.commit()
    return redirect(url_for('dashboard.practice', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/tests', methods=['POST'])
@login_required
def schedule_test(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    title = request.form.get("title", "Mock Test")
    test_type = request.form.get("test_type", "mock")
    if test_type not in {"diagnostic", "sectional", "full_length", "revision", "essay", "interview", "mock"}:
        test_type = "mock"
    date_str = request.form.get("scheduled_date")
    duration = int(request.form.get("duration_minutes", 90) or 90)
    qcount = int(request.form.get("questions_count", 50) or 50)
    notes = request.form.get("notes", "").strip() or None
    try:
        scheduled_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        scheduled_date = _utc_today()
    test = MockTestSchedule(
        title=title,
        test_type=test_type,
        scheduled_date=scheduled_date,
        duration_minutes=duration,
        questions_count=qcount,
        notes=notes,
        roadmap_id=roadmap.id
    )
    db.session.add(test)
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/tests/<int:test_id>/status', methods=['POST'])
@login_required
def update_test_status(roadmap_id, test_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    test = MockTestSchedule.query.get_or_404(test_id)
    if roadmap.user_id != session['user_id'] or test.roadmap_id != roadmap.id:
        return redirect(url_for('dashboard.dashboard'))
    status = request.form.get("status", "planned")
    if status not in ["planned", "completed", "missed"]:
        status = "planned"
    test.status = status
    score_val = request.form.get("score", "").strip()
    if score_val:
        try:
            test.score = float(score_val)
        except ValueError:
            pass
    test.notes = request.form.get("notes", "").strip() or test.notes
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/api/roadmap/<int:roadmap_id>/generate-test')
@login_required
def api_generate_test(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return {"error": "unauthorized"}, 403
    questions = _fetch_opentdb_questions(amount=10, difficulty="medium")
    if not questions:
        topics = [t.title for t in Task.query.filter_by(roadmap_id=roadmap.id).limit(10).all()]
        questions = [
            {
                "question": f"Explain the key ideas in {topic}.",
                "options": ["Definition", "Example", "Counterpoint", "Summary"],
                "answer": "Summary"
            }
            for topic in topics[:10]
        ]
    return {"questions": questions}


@dashboard_bp.route('/questions/<int:question_id>/attempt', methods=['POST'])
@login_required
def attempt_question(question_id):
    question = Question.query.get_or_404(question_id)
    score = int(request.form.get('score', 0))
    score = max(0, min(5, score))
    notes = request.form.get('notes', '').strip() or None
    attempt = QuestionAttempt(
        score=score,
        notes=notes,
        user_id=session['user_id'],
        question_id=question.id
    )
    db.session.add(attempt)
    db.session.commit()
    return redirect(request.referrer or url_for('dashboard.dashboard'))


@dashboard_bp.route('/api/roadmap/<int:roadmap_id>/questions')
@login_required
def api_questions(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return {"error": "unauthorized"}, 403
    _ensure_upsc_question_bank()
    questions = Question.query.filter_by(exam="UPSC").limit(100).all()
    payload = [
        {
            "id": q.id,
            "exam": q.exam,
            "subject": q.subject,
            "topic": q.topic,
            "question": q.question_text,
            "answer": q.answer_text,
            "difficulty": q.difficulty
        }
        for q in questions
    ]
    return {"questions": payload}


@dashboard_bp.route('/api/questions/<int:question_id>/attempt', methods=['POST'])
@login_required
def api_attempt(question_id):
    question = Question.query.get_or_404(question_id)
    data = request.get_json(silent=True) or {}
    score = int(data.get("score", 0))
    score = max(0, min(5, score))
    notes = data.get("notes")
    attempt = QuestionAttempt(
        score=score,
        notes=notes,
        user_id=session['user_id'],
        question_id=question.id
    )
    db.session.add(attempt)
    db.session.commit()
    return {"status": "ok", "attempt_id": attempt.id}


@dashboard_bp.route('/roadmap/<int:roadmap_id>/checkin', methods=['POST'])
@login_required
def checkin(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    minutes = int(request.form.get('minutes', 0) or 0)
    note = request.form.get('note', '').strip() or None
    load_feel = request.form.get('load_feel', '').strip()
    confidence = request.form.get('confidence', '').strip()
    note_parts = []
    if note:
        note_parts.append(note)
    if load_feel:
        note_parts.append(f"Load:{load_feel}")
    if confidence:
        note_parts.append(f"Confidence:{confidence}")
    note = " | ".join(note_parts) if note_parts else None
    today = _utc_today()
    checkin = Checkin(checkin_date=today, minutes=minutes, note=note, roadmap_id=roadmap.id)
    db.session.add(checkin)
    _update_streak(roadmap, today)
    _auto_adjust_roadmap_timeline(roadmap)
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
    if task.last_resource_refresh and (_utc_now().replace(tzinfo=None) - task.last_resource_refresh).days < refresh_days:
        flash("Resources were refreshed recently. Try again later.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    Resource.query.filter_by(task_id=task.id).delete()
    if roadmap.roadmap_type == "upsc":
        resources = _curated_upsc_resources_for_task(task.title, _extract_optional_subject_from_source_text(roadmap.source_text))
    else:
        resources = _fetch_resources_for_topic(task.title.replace("Project: ", ""))
    for res in resources:
        db.session.add(Resource(
            provider=res["provider"],
            title=res["title"],
            url=res["url"],
            summary=res.get("use_case") or res.get("summary", ""),
            score=res.get("score", 0.95 if roadmap.roadmap_type == "upsc" else 0.0),
            task_id=task.id
        ))
    task.last_resource_refresh = _utc_now().replace(tzinfo=None)
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


@dashboard_bp.route('/roadmap/<int:roadmap_id>/export/summary.txt')
@login_required
def export_summary(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    lines = [
        f"Roadmap: {roadmap.title}",
        f"Type: {roadmap.roadmap_type}",
        f"Timeline: {roadmap.start_date} to {roadmap.target_date}",
        f"Progress: {roadmap.completed_tasks}/{roadmap.total_tasks}",
        "",
        "Key tasks:",
    ]
    lines.extend([f"- {task.title} ({task.status})" for task in tasks[:15]])
    content = "\n".join(lines)
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=True, download_name="roadmap-summary.txt")


@dashboard_bp.route('/roadmap/<int:roadmap_id>/export/revision.txt')
@login_required
def export_revision(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    revision_tasks = [task for task in tasks if "revision" in _normalize(task.title)]
    lines = [f"Revision Sheet: {roadmap.title}", ""]
    if not revision_tasks:
        lines.append("No explicit revision blocks are in this roadmap yet.")
    else:
        lines.extend([f"- {task.title} | Due {task.due_date or 'Flexible'}" for task in revision_tasks])
    content = "\n".join(lines)
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=True, download_name="revision-sheet.txt")


@dashboard_bp.route('/roadmap/<int:roadmap_id>/export/monthly-review.txt')
@login_required
def export_monthly_review(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    tests = MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).order_by(MockTestSchedule.scheduled_date.asc()).all() if _has_table("mock_test_schedule") else []
    review = _build_monthly_review(roadmap, tasks, tests)
    story = _build_progress_story(roadmap, {}, [])
    lines = [
        f"Monthly Review: {roadmap.title}",
        "",
        f"Headline: {review['headline']}",
        f"Summary: {review['summary']}",
        f"Tasks completed: {review['tasks_completed']}",
        f"Minutes logged: {review['minutes_logged']}",
        f"Active tasks: {review['active_tasks']}",
        f"Overdue tasks: {review['overdue_count']}",
        "",
        "Progress story:",
    ]
    lines.extend([f"- {item}" for item in story])
    content = "\n".join(lines)
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=True, download_name="monthly-review.txt")


@dashboard_bp.route('/roadmap/<int:roadmap_id>/export/interview.txt')
@login_required
def export_interview(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    prompts = [task.title for task in tasks if any(marker in _normalize(task.title) for marker in ["project", "portfolio", "interview", "case study", "resume"])]
    lines = [f"Interview Prep Snapshot: {roadmap.title}", ""]
    if prompts:
        for item in prompts[:12]:
            lines.append(f"- Tell the story of: {item}")
    else:
        lines.append("No interview-ready proof tasks found yet. Add project, portfolio, or proof tasks to strengthen this export.")
    content = "\n".join(lines)
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=True, download_name="interview-snapshot.txt")


@dashboard_bp.route('/roadmap/<int:roadmap_id>/rebalance', methods=['POST'])
@login_required
def rebalance(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    remaining_tasks = Task.query.filter_by(roadmap_id=roadmap.id).filter(Task.status != "done").order_by(Task.order_index.asc()).all()
    if not remaining_tasks:
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    timeline_weeks = int(request.form.get('timeline_weeks', 0) or 0)
    _auto_adjust_roadmap_timeline(roadmap, start_date=_utc_today(), timeline_weeks=timeline_weeks)
    db.session.commit()
    return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/delete', methods=['POST'])
@login_required
def delete_roadmap(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    db.session.query(Roadmap).filter_by(id=roadmap_id).delete(synchronize_session=False)
    db.session.commit()
    return redirect(url_for('dashboard.dashboard'))


def _resolve_upsc_subjects(focus="full_journey", selected_subjects=None):
    selected_subjects = selected_subjects or []
    resolved = [key for key in selected_subjects if key in UPSC_SUBJECT_LIBRARY]
    if resolved:
        return resolved
    return list(UPSC_DEFAULT_SUBJECTS_BY_FOCUS.get(focus, UPSC_DEFAULT_SUBJECTS_BY_FOCUS["full_journey"]))


def _compose_upsc_source_text(selected_subjects, optional_subject, focus, personalization_notes=""):
    labels = [UPSC_SUBJECT_LIBRARY[key]["label"] for key in selected_subjects if key in UPSC_SUBJECT_LIBRARY]
    guidance = UPSC_OFFICIAL_GUIDANCE.get(focus, UPSC_OFFICIAL_GUIDANCE["full_journey"])
    lines = [
        f"UPSC Focus: {focus}",
        f"Selected Subjects: {', '.join(labels) if labels else 'Default UPSC track'}",
        "Official Strategy Anchors:",
    ]
    lines.extend([f"- {item}" for item in guidance])
    if optional_subject:
        lines.append(f"Optional Subject: {optional_subject}")
    if personalization_notes:
        lines.append("Aspirant Notes:")
        lines.append(personalization_notes[:1500])
    return "\n".join(lines)


def _build_upsc_subject_plan(selected_subjects, optional_subject="", focus="full_journey"):
    resolved = _resolve_upsc_subjects(focus, selected_subjects)
    topics = []
    for key in resolved:
        topics.extend(UPSC_SUBJECT_LIBRARY[key]["topics"])
    if optional_subject:
        topics.append(f"Optional subject deep dive: {optional_subject}")
        topics.append(f"Optional subject PYQ mapping: {optional_subject}")

    projects = [
        "Daily current affairs notes and weekly revision",
        "PYQ drill across selected papers",
        "Answer writing practice with self-review",
        "Mock test analysis and weak-area tracker",
    ]
    if "interview" in resolved and focus == "interview":
        projects = [
            "DAF question bank",
            "Mock interview reflections",
            "Current affairs speaking practice",
        ]

    unique_topics = []
    seen = set()
    for topic in topics:
        key = topic.lower()
        if key not in seen:
            seen.add(key)
            unique_topics.append(topic)
    return unique_topics, projects, resolved


def _upsc_resources_for_task(task_title, optional_subject=""):
    return _curated_upsc_resources_for_task(task_title, optional_subject)


def _build_upsc_test_plan(start_date, target_date, focus="full_journey"):
    total_days = max((target_date - start_date).days, 28)
    checkpoints = [0.2, 0.4, 0.6, 0.8, 0.92]
    tests = []

    if focus in ("full_journey", "prelims"):
        labels = [
            "UPSC Foundation Diagnostic Test",
            "Prelims Sectional Mock",
            "Prelims GS Full Mock",
            "CSAT Full Mock",
            "Final Prelims Revision Test",
        ]
    elif focus == "mains":
        labels = [
            "Mains GS Diagnostic",
            "Essay Practice Test",
            "GS Full-Length Mock",
            "Ethics Case Study Mock",
            "Final Mains Simulation",
        ]
    else:
        labels = [
            "DAF Diagnostic",
            "Current Affairs Panel Round",
            "Mock Interview 1",
            "Mock Interview 2",
            "Final Personality Test Drill",
        ]

    for ratio, label in zip(checkpoints, labels):
        scheduled_date = start_date + timedelta(days=max(7, math.floor(total_days * ratio)))
        if focus == "interview":
            test_type = "interview"
        elif "Essay" in label:
            test_type = "essay"
        elif "Diagnostic" in label:
            test_type = "diagnostic"
        elif "Sectional" in label:
            test_type = "sectional"
        elif "Revision" in label:
            test_type = "revision"
        else:
            test_type = "full_length"
        tests.append({
            "title": label,
            "test_type": test_type,
            "scheduled_date": min(scheduled_date, target_date),
            "duration_minutes": 120 if focus != "interview" else 45,
            "questions_count": 100 if "Prelims" in label or "CSAT" in label else 20 if focus == "interview" else 25,
        })
    return tests


def _classify_upsc_bucket(title):
    normalized = _normalize(title)
    prelims_markers = [
        "prelims", "csat", "environment", "ecology", "science and technology",
        "polity", "history", "geography", "economy", "ncert"
    ]
    mains_markers = [
        "essay", "general studies", "gs paper", "ethics", "answer writing",
        "mains", "governance", "international relations", "internal security", "optional subject"
    ]
    interview_markers = [
        "interview", "daf", "personality test", "panel round", "communication"
    ]

    if any(marker in normalized for marker in interview_markers):
        return "Interview"
    if any(marker in normalized for marker in mains_markers):
        return "Mains"
    if any(marker in normalized for marker in prelims_markers):
        return "Prelims"
    return "Foundation"


def _build_upsc_dashboard_data(tasks, tests):
    buckets = {
        "Foundation": {"tasks": [], "tests": [], "completed": 0, "total": 0, "test_completed": 0},
        "Prelims": {"tasks": [], "tests": [], "completed": 0, "total": 0, "test_completed": 0},
        "Mains": {"tasks": [], "tests": [], "completed": 0, "total": 0, "test_completed": 0},
        "Interview": {"tasks": [], "tests": [], "completed": 0, "total": 0, "test_completed": 0},
    }

    for task in tasks:
        bucket = _classify_upsc_bucket(task.title)
        buckets[bucket]["tasks"].append(task)
        buckets[bucket]["total"] += 1
        if task.status == "done":
            buckets[bucket]["completed"] += 1

    for test in tests:
        bucket = _classify_upsc_bucket(test.title)
        buckets[bucket]["tests"].append(test)
        if test.status == "completed":
            buckets[bucket]["test_completed"] += 1

    ordered = []
    for name in ["Foundation", "Prelims", "Mains", "Interview"]:
        bucket = buckets[name]
        progress = round((bucket["completed"] / bucket["total"]) * 100, 2) if bucket["total"] else 0
        ordered.append({
            "name": name,
            "tasks": bucket["tasks"],
            "tests": bucket["tests"],
            "completed": bucket["completed"],
            "total": bucket["total"],
            "progress": progress,
            "test_completed": bucket["test_completed"],
            "test_total": len(bucket["tests"]),
        })
    return ordered


def _persist_roadmap(roadmap_type, title, raw_text, topics, projects, start_date, timeline_weeks,
                     hours_per_week, study_days_per_week, upsc_focus="", upsc_optional_subject="", pace_mode="steady"):
    task_specs, total_hours, computed_end = _build_tasks(
        roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week, study_days_per_week, pace_mode, raw_text
    )
    target_date = computed_end

    roadmap = Roadmap(
        title=title,
        roadmap_type=roadmap_type,
        source_text=(raw_text or f"UPSC Focus: {upsc_focus}\nOptional Subject: {upsc_optional_subject}")[:5000],
        start_date=start_date,
        target_date=target_date,
        total_tasks=len(task_specs),
        completed_tasks=0,
        total_hours_est=total_hours,
        hours_per_week=hours_per_week,
        study_days_per_week=study_days_per_week,
        timezone=current_app.config.get("DEFAULT_TIMEZONE", "Asia/Kolkata"),
        resource_fetch_status="idle",
        user_id=session['user_id']
    )
    db.session.add(roadmap)
    db.session.flush()

    auto_fetch = current_app.config.get("AUTO_FETCH_RESOURCES_ON_CREATE", False)
    task_ids = []
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
        task_ids.append(task.id)

        if auto_fetch:
            task.last_resource_refresh = None

    db.session.commit()
    return roadmap, task_ids, auto_fetch, target_date


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
