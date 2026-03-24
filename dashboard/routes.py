from flask import Blueprint, render_template, request, redirect, session, url_for, current_app, flash, send_file
from extensions import db
from models.models import User, Roadmap, Task, Resource, ResourceFeedback, Checkin, Question, QuestionAttempt, PyqCompletion, MockTestSchedule, QuizResult
from datetime import datetime, timedelta, date
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
        return fallback or datetime.utcnow().date()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback or datetime.utcnow().date()


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
            default=date.today()
        )
        roadmap.target_date = last_completed
        roadmap.total_hours_est = round(completed_hours, 1)
        return

    schedule_start = start_date or date.today()
    task_specs, remaining_hours, computed_end = _schedule_items(
        [task.title for task in remaining_tasks],
        schedule_start,
        timeline_weeks,
        roadmap.hours_per_week,
        roadmap.study_days_per_week
    )

    for task, spec in zip(remaining_tasks, task_specs):
        task.due_date = spec["due_date"]
        task.estimated_hours = spec["estimated_hours"]

    roadmap.target_date = computed_end
    roadmap.total_hours_est = round(completed_hours + remaining_hours, 1)


def _build_recent_updates(roadmap):
    updates = []

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


def _build_today_focus(roadmap, tasks, tests):
    today = date.today()
    next_task = next((task for task in tasks if task.status != "done"), None)
    upcoming_tests = [test for test in tests if test.status != "completed" and test.scheduled_date >= today]
    next_test = upcoming_tests[0] if upcoming_tests else None

    due_soon = [task for task in tasks if task.status != "done" and task.due_date and task.due_date <= today + timedelta(days=3)]
    revision_task = next(
        (task for task in tasks if task.status != "done" and any(marker in _normalize(task.title) for marker in ["revision", "pyq", "answer writing", "mock", "essay"])),
        None
    )

    return {
        "next_task": next_task,
        "next_test": next_test,
        "revision_task": revision_task or next_task,
        "due_soon_count": len(due_soon),
    }


def _build_week_plan(tasks, tests):
    today = date.today()
    week_end = today + timedelta(days=7)
    week_tasks = [task for task in tasks if task.status != "done" and task.due_date and today <= task.due_date <= week_end][:5]
    week_tests = [test for test in tests if today <= test.scheduled_date <= week_end][:3]
    return {"tasks": week_tasks, "tests": week_tests}


def _build_resource_groups(resources):
    groups = {
        "Start here": [],
        "Official source": [],
        "Deep study": [],
        "Quick revision": [],
    }

    for res in resources:
        provider = ((res.get("provider") if isinstance(res, dict) else res.provider) or "").lower()
        title = _normalize((res.get("title") if isinstance(res, dict) else res.title) or "")
        summary = _normalize((res.get("summary") if isinstance(res, dict) else res.summary) or "")

        if provider in {"upsc", "official", "ncert"}:
            target = "Official source"
        elif any(marker in title or marker in summary for marker in ["summary", "outline", "quick", "revision", "notes"]):
            target = "Quick revision"
        elif provider in {"crossref", "research"} or any(marker in title for marker in ["analysis", "advanced", "deep"]):
            target = "Deep study"
        else:
            target = "Start here"
        groups[target].append(res)

    ordered = []
    for label in ["Start here", "Official source", "Deep study", "Quick revision"]:
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
        "tags": tags,
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


def _build_tasks(roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week, study_days_per_week):
    all_items = topics[:]
    if roadmap_type in {"career", "upsc"}:
        for project in projects:
            all_items.append(f"Project: {project}")
    return _schedule_items(all_items, start_date, timeline_weeks, hours_per_week, study_days_per_week)


def _background_fetch_resources(app, roadmap_id):
    with app.app_context():
        if not current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
            return
        roadmap = Roadmap.query.get(roadmap_id)
        if not roadmap:
            return
        try:
            roadmap.resource_fetch_status = "running"
            roadmap.resource_fetch_started_at = datetime.utcnow()
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
                task.last_resource_refresh = datetime.utcnow()
            roadmap.resource_fetch_status = "done"
            roadmap.resource_fetch_completed_at = datetime.utcnow()
            db.session.commit()
        except Exception:
            roadmap.resource_fetch_status = "failed"
            db.session.commit()
        finally:
            db.session.remove()


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
        try:
            title = request.form.get('title', '').strip()
            roadmap_type = request.form.get('roadmap_type', 'syllabus')
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

            roadmap, task_ids, auto_fetch, _ = _persist_roadmap(
                roadmap_type, title, raw_text, topics, projects, start_date, timeline_weeks,
                hours_per_week, study_days_per_week
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
            raw_text = _compose_upsc_source_text(upsc_subjects, upsc_optional_subject, upsc_focus, personalization_notes)

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
                hours_per_week, study_days_per_week, upsc_focus, upsc_optional_subject
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
                for spec in _build_upsc_test_plan(start_date, target_date, upsc_focus):
                    db.session.add(MockTestSchedule(
                        title=spec["title"],
                        test_type=spec["test_type"],
                        scheduled_date=spec["scheduled_date"],
                        duration_minutes=spec["duration_minutes"],
                        questions_count=spec["questions_count"],
                        roadmap_id=roadmap.id
                    ))
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
    tests = MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).order_by(MockTestSchedule.scheduled_date.asc()).all()
    upsc_buckets = _build_upsc_dashboard_data(tasks, tests) if roadmap.roadmap_type == "upsc" else []
    recent_updates = _build_recent_updates(roadmap)
    done_map = {}
    attempts = {}
    quiz_results = []
    if roadmap.roadmap_type == "upsc":
        for c in PyqCompletion.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).all():
            done_map.setdefault(c.exam, []).append(c.year)
        attempts = {a.question_id: a for a in QuestionAttempt.query.filter_by(user_id=session['user_id']).all()}
        quiz_results = QuizResult.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).order_by(QuizResult.attempted_at.desc()).limit(5).all()
    today_focus = _build_today_focus(roadmap, tasks, tests)
    week_plan = _build_week_plan(tasks, tests)
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
    _ensure_upsc_question_bank()
    questions = Question.query.filter_by(exam="UPSC").limit(60).all()
    attempts = {a.question_id: a for a in QuestionAttempt.query.filter_by(user_id=session['user_id']).all()}
    current_year = datetime.utcnow().year
    years = list(range(current_year - 9, current_year + 1))
    completions = PyqCompletion.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).all()
    done_map = {}
    for c in completions:
        done_map.setdefault(c.exam, []).append(c.year)
    pyq_total = sum(len(items) for items in done_map.values())
    avg_score = round(sum(a.score for a in attempts.values()) / max(len(attempts), 1), 1) if attempts else 0.0
    readiness_metrics = _build_readiness_metrics(
        roadmap,
        Task.query.filter_by(roadmap_id=roadmap.id).all(),
        MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).all(),
        done_map,
        attempts,
        QuizResult.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).order_by(QuizResult.attempted_at.desc()).limit(5).all()
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
        readiness_metrics=readiness_metrics
    )


@dashboard_bp.route('/roadmap/<int:roadmap_id>/quiz', methods=['GET'])
@login_required
def quiz(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
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
    return render_template("quiz_result.html", roadmap=roadmap, result=result, accuracy=accuracy, analysis=analysis)


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
        scheduled_date = datetime.utcnow().date()
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
    today = date.today()
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
    if task.last_resource_refresh and (datetime.utcnow() - task.last_resource_refresh).days < refresh_days:
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

    timeline_weeks = int(request.form.get('timeline_weeks', 0) or 0)
    _auto_adjust_roadmap_timeline(roadmap, start_date=datetime.utcnow().date(), timeline_weeks=timeline_weeks)
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
                     hours_per_week, study_days_per_week, upsc_focus="", upsc_optional_subject=""):
    task_specs, total_hours, computed_end = _build_tasks(
        roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week, study_days_per_week
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
