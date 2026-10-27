from flask import Blueprint, render_template, request, redirect, session, url_for, current_app, flash, send_file, jsonify
from extensions import db
from models.models import User, Roadmap, Task, Resource, ResourceFeedback, Checkin, Question, QuestionAttempt, PyqCompletion, MockTestSchedule, QuizResult, QuizQuestion, QuizQuestionAttempt
from dashboard.nl_plan import parse_plan_text
from datetime import datetime, timedelta, date, UTC
from werkzeug.utils import secure_filename
from urllib.parse import quote
import os
import re
import csv
import io
import json
import math
import random
import requests
import threading
from supabase import create_client
from sqlalchemy import inspect
from security import rate_limit
from pyq import (
    OFFICIAL_ANSWER_KEY_URL,
    OFFICIAL_PYQ_URL,
    PYQ_ATTRIBUTION,
    coverage_stats,
    ensure_pyq_synced,
    get_interview_set,
    mains_questions,
    prelims_questions,
    subject_keywords_for_topics,
)

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


def _is_admin():
    user_id = session.get('user_id')
    allowed = current_app.config.get('ADMIN_EMAILS') or []
    if not user_id or not allowed:
        return False
    user = User.query.get(user_id)
    return bool(user and user.email and user.email.lower() in allowed)


def _has_table(table_name):
    return table_name in _available_tables()


def _table_columns(table_name):
    if not _has_table(table_name):
        return set()
    try:
        return {column["name"] for column in inspect(db.engine).get_columns(table_name)}
    except Exception:
        return set()


def _has_columns(table_name, required_columns):
    columns = _table_columns(table_name)
    return bool(columns) and set(required_columns).issubset(columns)


def _has_mock_test_schedule_schema():
    return _has_columns(
        "mock_test_schedule",
        {
            "id",
            "title",
            "test_type",
            "scheduled_date",
            "duration_minutes",
            "questions_count",
            "status",
            "score",
            "notes",
            "created_at",
            "roadmap_id",
        },
    )


def _has_quiz_question_schema():
    return _has_columns(
        "quiz_question",
        {
            "id",
            "question_text",
            "options_json",
            "correct_answer",
            "category",
            "source",
            "difficulty",
            "mode",
            "created_at",
            "user_id",
            "roadmap_id",
        },
    )


def _has_quiz_question_attempt_schema():
    return _has_columns(
        "quiz_question_attempt",
        {"id", "selected_answer", "is_correct", "created_at", "quiz_result_id", "question_id"},
    )


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

CAREER_FAMILIES = {
    "software": {
        "label": "Software development",
        "topics": [
            "Programming fundamentals and problem solving",
            "Version control with Git and GitHub",
            "Data structures and algorithms essentials",
            "Web fundamentals: HTML, CSS, and JavaScript",
            "APIs and backend request handling",
            "Databases and data modeling",
            "Testing, debugging, and code review",
            "Deployment and CI/CD basics",
            "System design and architecture basics",
            "Security and performance essentials",
            "Collaboration workflow for real teams",
            "Portfolio and open-source contribution",
        ],
        "projects": [
            "{role} portfolio website",
            "Full-stack app with authentication and a database",
            "REST API with tests and documentation",
            "Capstone: deploy a real product end to end",
        ],
        "assignments": [
            "Solve 30 coding katas across easy and medium levels",
            "Build 3 reusable UI components and document them",
            "Write automated tests for one existing project",
            "Refactor a small codebase and record what improved",
            "Publish one project with setup instructions and a demo",
        ],
        "tools": ["Git and GitHub", "VS Code", "Postman", "Docker"],
        "outcome": "A deployable portfolio, tested projects, and interview-ready code explanations.",
    },
    "data": {
        "label": "Data and AI",
        "topics": [
            "Spreadsheet fluency and data hygiene",
            "SQL queries, joins, and window functions",
            "Python or R for data work",
            "Probability and statistics essentials",
            "Data cleaning and validation",
            "Exploratory data analysis",
            "Visualization and chart selection",
            "Dashboards and reporting",
            "Experimentation and A/B testing",
            "Business metrics and decision framing",
            "Storytelling with data",
            "Data ethics, privacy, and model evaluation",
        ],
        "projects": [
            "{role} analytics dashboard",
            "Customer churn or retention analysis",
            "Forecasting report with clear assumptions",
            "Capstone: end-to-end data pipeline and insight deck",
        ],
        "assignments": [
            "Write 20 SQL queries against a public dataset",
            "Clean a messy dataset and document every decision",
            "Build 3 charts that answer one business question",
            "Complete one statistics or Kaggle case study",
            "Present a 5-slide insight deck with recommendations",
        ],
        "tools": ["SQL", "Python (pandas)", "Excel or Google Sheets", "Power BI or Tableau"],
        "outcome": "A dashboard portfolio, SQL fluency, and business-ready insight stories.",
    },
    "design": {
        "label": "Design and UX",
        "topics": [
            "Design principles and visual hierarchy",
            "Typography and color systems",
            "Layout, spacing, and responsive grids",
            "User research and interview basics",
            "Information architecture and user flows",
            "Wireframing and low-fidelity prototyping",
            "High-fidelity prototyping and interaction design",
            "Design systems and component libraries",
            "Accessibility and inclusive design",
            "Usability testing and feedback synthesis",
            "Portfolio storytelling and case studies",
            "Client communication and design critique",
        ],
        "projects": [
            "{role} portfolio with 3 case studies",
            "End-to-end mobile app redesign",
            "Design system with reusable components",
            "Capstone: research-led product concept and prototype",
        ],
        "assignments": [
            "Recreate 3 strong interfaces and annotate the decisions",
            "Run 3 short user interviews and summarize insights",
            "Prototype one flow in Figma with interactive states",
            "Audit a real product for accessibility issues",
            "Write one case study with problem, process, and outcome",
        ],
        "tools": ["Figma", "FigJam", "Notion", "Maze or a usability test script"],
        "outcome": "A case-study portfolio, usable prototypes, and a repeatable design process.",
    },
    "product": {
        "label": "Product and project management",
        "topics": [
            "Customer discovery and problem framing",
            "Product requirements and user stories",
            "Roadmapping and prioritization",
            "Metrics, funnels, and success criteria",
            "Stakeholder communication",
            "Agile delivery and sprint planning",
            "Risk, scope, and dependency management",
            "Research synthesis and decision logs",
            "Launch planning and go-to-market basics",
            "Post-launch measurement and iteration",
            "Cross-functional collaboration",
            "Portfolio of product decisions",
        ],
        "projects": [
            "{role} product case study",
            "Feature proposal with metrics and rollout plan",
            "Delivery plan for a real team project",
            "Capstone: product strategy pack for a real problem",
        ],
        "assignments": [
            "Interview 5 users and write a discovery summary",
            "Write a PRD for one feature with clear acceptance criteria",
            "Build a simple metrics dashboard or tracker",
            "Run a mock sprint planning and retro",
            "Publish a case study with trade-offs and results",
        ],
        "tools": ["Notion", "Jira or Linear", "Miro", "Google Analytics basics"],
        "outcome": "A decision portfolio, delivery artifacts, and confident stakeholder storytelling.",
    },
    "marketing": {
        "label": "Marketing and content",
        "topics": [
            "Audience research and positioning",
            "Copywriting and messaging",
            "SEO and search intent",
            "Content planning and editorial calendars",
            "Social media and community strategy",
            "Email marketing and lifecycle campaigns",
            "Paid campaign fundamentals",
            "Analytics and attribution basics",
            "Brand voice and storytelling",
            "Conversion and landing-page optimization",
            "Public relations and outreach",
            "Campaign retrospectives",
        ],
        "projects": [
            "{role} content portfolio",
            "Full campaign plan for a real product",
            "SEO content cluster with 5 pieces",
            "Capstone: launch campaign with measured results",
        ],
        "assignments": [
            "Write 5 headlines and 3 landing-page variants",
            "Audit a website for SEO and messaging gaps",
            "Build a 2-week content calendar",
            "Design and send one mock email sequence",
            "Report campaign results with next-step recommendations",
        ],
        "tools": ["Google Analytics", "Google Search Console", "Canva", "Mailchimp"],
        "outcome": "A measurable campaign portfolio, strong writing samples, and growth evidence.",
    },
    "business": {
        "label": "Business and finance",
        "topics": [
            "Accounting and financial statement basics",
            "Budgeting and forecasting",
            "Excel modeling and analysis",
            "Market and competitor research",
            "Pricing and unit economics",
            "Risk and compliance basics",
            "Business writing and reporting",
            "Negotiation and client communication",
            "Operations and process improvement",
            "Data-informed decision making",
            "Case-study problem solving",
            "Professional ethics and judgment",
        ],
        "projects": [
            "{role} financial or business analysis",
            "Market entry or growth case study",
            "Budget model with scenarios",
            "Capstone: business plan with clear assumptions",
        ],
        "assignments": [
            "Build a 3-statement financial model",
            "Analyze one company and write an investment-style memo",
            "Create a budget with base, best, and worst cases",
            "Complete 3 business case studies under time pressure",
            "Present recommendations to a mock stakeholder",
        ],
        "tools": ["Excel or Google Sheets", "PowerPoint or Slides", "Power BI", "Accounting software basics"],
        "outcome": "A modeling portfolio, defensible recommendations, and client-ready communication.",
    },
    "healthcare": {
        "label": "Healthcare",
        "topics": [
            "Core anatomy, physiology, and terminology",
            "Patient communication and empathy",
            "Clinical workflows and documentation",
            "Infection control and patient safety",
            "Ethics, consent, and confidentiality",
            "Evidence-based practice and research reading",
            "Emergency response and escalation basics",
            "Medication or treatment safety basics",
            "Interprofessional collaboration",
            "Licensing and exam requirements",
            "Case-based clinical reasoning",
            "Professional wellbeing and resilience",
        ],
        "projects": [
            "{role} clinical case portfolio",
            "Patient-education resource on one condition",
            "Safety or quality improvement proposal",
            "Capstone: observed practice reflection and plan",
        ],
        "assignments": [
            "Complete 20 terminology and anatomy recall drills",
            "Write 3 patient-friendly explanations",
            "Shadow or interview a working professional",
            "Practice 5 clinical or licensing exam scenarios",
            "Document one case using a structured format",
        ],
        "tools": ["Medical reference apps", "Anatomy flashcards", "Clinical guidelines", "Licensing exam question banks"],
        "outcome": "Exam-ready knowledge, safe practice habits, and a reflective clinical portfolio.",
    },
    "education": {
        "label": "Education and training",
        "topics": [
            "Learning science and memory principles",
            "Curriculum and syllabus design",
            "Lesson planning and objectives",
            "Assessment and feedback design",
            "Classroom management and engagement",
            "Explaining complex ideas simply",
            "Accessibility and inclusive teaching",
            "Educational technology tools",
            "Parent and stakeholder communication",
            "Reflective teaching practice",
            "Subject-matter depth",
            "Teaching portfolio and demo lesson",
        ],
        "projects": [
            "{role} teaching portfolio",
            "Full unit plan with assessments",
            "Recorded demo lesson with reflection",
            "Capstone: learner-centered course or workshop",
        ],
        "assignments": [
            "Design 3 lesson plans with clear outcomes",
            "Create a formative assessment and rubric",
            "Record a 10-minute demo lesson",
            "Run a short learner feedback survey",
            "Build a 5-session mini course outline",
        ],
        "tools": ["Google Classroom", "Canva", "Kahoot or Quizizz", "Notion"],
        "outcome": "A teaching portfolio, confident demo lessons, and evidence of learner progress.",
    },
    "legal": {
        "label": "Legal",
        "topics": [
            "Legal reasoning and issue spotting",
            "Core constitutional and statutory concepts",
            "Legal research and citation",
            "Case reading and ratio extraction",
            "Legal writing and drafting",
            "Civil and criminal procedure basics",
            "Contract and negotiation fundamentals",
            "Client interviewing and ethics",
            "Moot court and oral advocacy",
            "Current legal developments",
            "Compliance and risk awareness",
            "Professional judgment under pressure",
        ],
        "projects": [
            "{role} legal research memo",
            "Draft contract or petition portfolio",
            "Moot court argument and written submission",
            "Capstone: case analysis with reasoned opinion",
        ],
        "assignments": [
            "Brief 10 leading cases in a structured format",
            "Draft one contract clause set with explanations",
            "Complete 3 timed issue-spotting exercises",
            "Prepare and deliver a 5-minute moot argument",
            "Summarize one recent judgment and its impact",
        ],
        "tools": ["Legal research databases", "Citation guides", "Case-brief templates", "Moot court recordings"],
        "outcome": "A writing portfolio, research fluency, and confident oral advocacy practice.",
    },
    "engineering": {
        "label": "Engineering",
        "topics": [
            "Mathematics and physics foundations",
            "Engineering drawing and CAD",
            "Materials and mechanics basics",
            "Core systems and components",
            "Measurement and instrumentation",
            "Standards, codes, and safety",
            "Simulation and analysis tools",
            "Design reviews and documentation",
            "Manufacturing or construction processes",
            "Project planning and cost awareness",
            "Quality and reliability",
            "Professional engineering practice",
        ],
        "projects": [
            "{role} design project",
            "CAD model and tolerance study",
            "Analysis report with calculations",
            "Capstone: build or simulate a working system",
        ],
        "assignments": [
            "Complete 20 core calculation drills",
            "Produce one full engineering drawing set",
            "Run a simulation and explain the results",
            "Write a design review document",
            "Conduct a safety and failure-mode review",
        ],
        "tools": ["AutoCAD or SolidWorks", "MATLAB or Python", "Excel", "Simulation software"],
        "outcome": "A design portfolio, defensible calculations, and standards-aware documentation.",
    },
    "public_service": {
        "label": "Public service",
        "topics": [
            "Policy and governance fundamentals",
            "Constitution, law, and institutions",
            "Economics and public finance",
            "Current affairs and issue mapping",
            "Essay and answer writing",
            "Ethics and integrity in public life",
            "Data interpretation and reasoning",
            "Public administration concepts",
            "Interview and personality test readiness",
            "Mock tests and previous-year questions",
            "Optional or specialist subject depth",
            "Revision and note-making systems",
        ],
        "projects": [
            "{role} preparation system",
            "Policy brief on a current issue",
            "Full-length mock test sprint",
            "Capstone: interview-ready profile and notes",
        ],
        "assignments": [
            "Write 10 structured answers under timed conditions",
            "Summarize 5 weeks of current affairs",
            "Complete 2 full-length mock tests",
            "Prepare one policy brief with recommendations",
            "Record and review a mock interview",
        ],
        "tools": ["Official syllabus and PYQs", "Newspaper or PIB", "Mock test series", "Revision notebooks"],
        "outcome": "Exam-ready notes, timed writing stamina, and confident interview communication.",
    },
    "operations": {
        "label": "Operations and supply chain",
        "topics": [
            "Process mapping and improvement",
            "Supply chain and inventory basics",
            "Quality management and metrics",
            "Vendor and stakeholder management",
            "Project coordination and scheduling",
            "Cost control and efficiency",
            "Health, safety, and compliance",
            "Logistics and distribution",
            "Data tracking and reporting",
            "ERP and spreadsheet tools",
            "Risk and continuity planning",
            "Team communication and escalation",
        ],
        "projects": [
            "{role} process improvement case",
            "Inventory or scheduling model",
            "Vendor evaluation and scorecard",
            "Capstone: operations plan for a real workflow",
        ],
        "assignments": [
            "Map one real process end to end",
            "Build a simple demand or inventory sheet",
            "Create a vendor scorecard with criteria",
            "Run a root-cause analysis on a failure case",
            "Draft a 30-day operational improvement plan",
        ],
        "tools": ["Excel or Google Sheets", "ERP basics", "Process maps", "Project trackers"],
        "outcome": "A process improvement portfolio, measurable efficiency thinking, and coordination confidence.",
    },
    "science": {
        "label": "Science and research",
        "topics": [
            "Literature review and source evaluation",
            "Research methods and study design",
            "Statistics for research",
            "Lab or field techniques",
            "Data recording and reproducibility",
            "Scientific writing and structure",
            "Research ethics and safety",
            "Presentation and poster design",
            "Grant or proposal writing",
            "Critical analysis of evidence",
            "Collaboration and peer review",
            "Career pathways in research",
        ],
        "projects": [
            "{role} research proposal",
            "Literature review and evidence map",
            "Small experiment or field study report",
            "Capstone: conference-style poster and abstract",
        ],
        "assignments": [
            "Read and summarize 10 key papers",
            "Write one literature review section",
            "Design a study with sampling and limitations",
            "Analyze a public dataset and report findings",
            "Present a 5-minute research pitch",
        ],
        "tools": ["Reference manager", "Python or R", "Lab notebook", "Presentation software"],
        "outcome": "A research portfolio, evidence-based writing, and presentation-ready findings.",
    },
    "hospitality": {
        "label": "Hospitality and customer experience",
        "topics": [
            "Service excellence and guest mindset",
            "Clear communication and active listening",
            "Conflict resolution and de-escalation",
            "Front desk and booking workflows",
            "Food safety and hygiene basics",
            "Health, safety, and emergency procedures",
            "Sales, upselling, and guest recovery",
            "Team coordination under pressure",
            "Cultural awareness and inclusivity",
            "Complaint handling and service recovery",
            "Brand standards and professionalism",
            "Career portfolio and interview stories",
        ],
        "projects": [
            "{role} service improvement case",
            "Guest journey map with pain points",
            "Staff training mini-module",
            "Capstone: service recovery playbook",
        ],
        "assignments": [
            "Role-play 5 difficult guest scenarios",
            "Audit one guest journey end to end",
            "Write a service recovery script",
            "Complete a food safety or safety checklist",
            "Interview one experienced professional",
        ],
        "tools": ["POS or booking system basics", "Service checklists", "Customer feedback forms", "Excel"],
        "outcome": "Guest-ready communication, service recovery skill, and a professional portfolio.",
    },
    "general": {
        "label": "Professional foundation",
        "topics": [
            "{role} foundations and terminology",
            "{role} tools and daily workflows",
            "Communication and professional writing",
            "Research and information literacy",
            "Problem solving and critical thinking",
            "Time management and prioritization",
            "Working with stakeholders",
            "Quality standards and ethics",
            "Data and spreadsheet basics",
            "Presentation and storytelling",
            "Networking and professional presence",
            "Interview preparation and career stories",
        ],
        "projects": [
            "{role} portfolio or work samples",
            "{role} case study on a real problem",
            "{role} 30-60-90 day plan",
            "Capstone: end-to-end {role} project with proof",
        ],
        "assignments": [
            "Research 10 job descriptions and extract repeat requirements",
            "Build a toolkit checklist for the role",
            "Complete 3 practice briefs or scenarios",
            "Talk to 2 people working in the role",
            "Write a 30-60-90 day plan with measurable goals",
        ],
        "tools": ["Excel or Google Sheets", "A notes system", "LinkedIn", "A portfolio page"],
        "outcome": "A tailored portfolio, role-specific vocabulary, and a credible interview story.",
    },
}

CAREER_FAMILY_ALIASES = {
    "software engineer": "software", "software developer": "software", "frontend developer": "software",
    "front end developer": "software", "front-end developer": "software", "backend developer": "software",
    "back end developer": "software", "back-end developer": "software", "full stack developer": "software",
    "fullstack developer": "software", "web developer": "software", "web development": "software",
    "mobile developer": "software", "android developer": "software", "ios developer": "software",
    "app developer": "software", "game developer": "software", "qa engineer": "software",
    "test engineer": "software", "devops engineer": "software", "cloud engineer": "software",
    "site reliability engineer": "software", "embedded engineer": "software", "firmware engineer": "software",
    "programmer": "software", "coding": "software", "developer": "software",
    "data scientist": "data", "data analyst": "data", "data engineer": "data", "data science": "data",
    "machine learning engineer": "data", "machine learning": "data", "ml engineer": "data",
    "ai engineer": "data", "artificial intelligence": "data", "analytics engineer": "data",
    "business intelligence": "data", "bi analyst": "data", "statistician": "data",
    "deep learning": "data", "nlp engineer": "data", "computer vision": "data",
    "product designer": "design", "ux designer": "design", "ui designer": "design",
    "interaction designer": "design", "visual designer": "design", "graphic designer": "design",
    "web designer": "design", "motion designer": "design", "animator": "design",
    "illustrator": "design", "ux": "design", "ui": "design",
    "product manager": "product", "project manager": "product", "program manager": "product",
    "scrum master": "product", "product owner": "product", "business analyst": "product",
    "management consultant": "product", "consultant": "product",
    "digital marketing": "marketing", "content writer": "marketing", "copywriter": "marketing",
    "social media": "marketing", "brand manager": "marketing", "growth marketer": "marketing",
    "content strategist": "marketing", "email marketing": "marketing", "performance marketing": "marketing",
    "public relations": "marketing", "marketing": "marketing", "seo": "marketing",
    "financial analyst": "business", "investment banker": "business", "accountant": "business",
    "accounting": "business", "auditor": "business", "economist": "business",
    "business development": "business", "human resources": "business", "recruiter": "business",
    "entrepreneur": "business", "founder": "business", "banker": "business",
    "insurance": "business", "sales engineer": "business", "sales": "business", "finance": "business",
    "registered nurse": "healthcare", "nurse": "healthcare", "nursing": "healthcare",
    "physician": "healthcare", "doctor": "healthcare", "pharmacist": "healthcare",
    "dentist": "healthcare", "physiotherapist": "healthcare", "psychologist": "healthcare",
    "counselor": "healthcare", "nutritionist": "healthcare", "veterinarian": "healthcare",
    "surgeon": "healthcare", "healthcare": "healthcare", "clinical": "healthcare",
    "instructional designer": "education", "teacher": "education", "tutor": "education",
    "professor": "education", "educator": "education", "trainer": "education",
    "lecturer": "education", "teaching": "education",
    "paralegal": "legal", "lawyer": "legal", "advocate": "legal", "legal": "legal",
    "compliance officer": "legal", "judge": "legal", "law": "legal",
    "civil engineer": "engineering", "mechanical engineer": "engineering", "electrical engineer": "engineering",
    "electronics engineer": "engineering", "chemical engineer": "engineering",
    "aerospace engineer": "engineering", "industrial engineer": "engineering",
    "automobile engineer": "engineering", "structural engineer": "engineering",
    "quantity surveyor": "engineering", "architect": "engineering", "engineer": "engineering",
    "civil services": "public_service", "public administration": "public_service",
    "public service": "public_service", "government": "public_service", "police": "public_service",
    "defence": "public_service", "defense": "public_service", "air force": "public_service",
    "army": "public_service", "navy": "public_service", "upsc": "public_service",
    "supply chain": "operations", "logistics": "operations", "project coordinator": "operations",
    "operations": "operations", "quality": "operations", "production": "operations",
    "warehouse": "operations", "facilities": "operations", "procurement": "operations",
    "inventory": "operations",
    "research scientist": "science", "scientist": "science", "researcher": "science",
    "biologist": "science", "chemist": "science", "physicist": "science",
    "biotechnology": "science", "microbiologist": "science", "research": "science", "phd": "science",
    "customer service": "hospitality", "customer support": "hospitality", "hospitality": "hospitality",
    "hotel": "hospitality", "tourism": "hospitality", "chef": "hospitality",
    "event manager": "hospitality", "flight attendant": "hospitality", "receptionist": "hospitality",
    "travel": "hospitality",
}
CAREER_FAMILY_ALIASES = sorted(CAREER_FAMILY_ALIASES.items(), key=lambda pair: len(pair[0]), reverse=True)

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


def _safe_float(value, default, minimum=None, maximum=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return round(parsed, 1)


def _study_dates(start_date, total_days, study_days_per_week):
    """Study dates use fixed weekdays so the plan is predictable."""
    study_days_per_week = _safe_int(study_days_per_week, 5, 1, 7)
    total_days = max(int(total_days or 1), 1)
    dates = []
    cursor = start_date
    end = start_date + timedelta(days=total_days - 1)
    while cursor <= end:
        if cursor.weekday() < study_days_per_week:
            dates.append(cursor)
        cursor += timedelta(days=1)
    return dates or [start_date]


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


def _replace_metadata_line(raw_text, label, value):
    base = (raw_text or "").strip()
    line = f"{label}: {value}"
    pattern = re.compile(rf"^{re.escape(label)}:\s*.*$", re.MULTILINE | re.IGNORECASE)
    if pattern.search(base):
        return pattern.sub(lambda _match: line, base, count=1)
    return f"{base}\n{line}".strip()


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


_SYLLABUS_MODULE_HEADING_RE = re.compile(
    r"^(?:unit|module|chapter|week|part|section|paper)\s*(?:no\.?)?\s*[-–—:.]?\s*"
    r"(?:\d{1,2}|[ivxlcdm]{1,6}|[a-z])\b",
    re.IGNORECASE,
)
_SYLLABUS_MODULE_ONLY_RE = re.compile(
    r"^(?:unit|module|chapter|week|part|section|paper)\s*(?:no\.?)?\s*[-–—:.]?\s*"
    r"(?:\d{1,2}|[ivxlcdm]{1,6}|[a-z])\s*[:\-–—.]*$",
    re.IGNORECASE,
)
_SYLLABUS_CONTENTS_RE = re.compile(
    r"^(?:course\s+contents?|course\s+topics?|syllabus|curriculum|topics?|contents?)\s*[:\-–—]?\s*$",
    re.IGNORECASE,
)
_SYLLABUS_ADMIN_HEADING_RE = re.compile(
    r"^(?:"
    r"course\s+(?:objectives?|outcomes?|description|code|title|structure|delivery|policy|information)"
    r"|program(?:me)?\s+outcomes?"
    r"|learning\s+outcomes?"
    r"|expected\s+outcomes?"
    r"|teaching\s+scheme"
    r"|examination\s+scheme"
    r"|assessment\s+(?:scheme|pattern|methods?|criteria|details|plan)"
    r"|evaluation\s+(?:scheme|pattern|criteria|methods?)"
    r"|grading(?:\s+policy)?"
    r"|attendance"
    r"|prerequisites?"
    r"|co-?requisites?"
    r"|text\s*books?"
    r"|reference\s+books?"
    r"|recommended\s+(?:reading|books?)"
    r"|required\s+reading"
    r"|suggested\s+reading"
    r"|further\s+reading"
    r"|reading\s+list"
    r"|web\s+resources"
    r"|online\s+resources"
    r"|faculty"
    r"|instructor"
    r"|course\s+coordinator"
    r"|contact\s+(?:details|information)"
    r"|office\s+hours"
    r"|academic\s+integrity"
    r"|plagiarism"
    r"|grievance"
    r"|mode\s+of\s+(?:examination|assessment)"
    r"|scheme\s+of\s+(?:examination|evaluation)"
    r"|list\s+of\s+(?:experiments|practical)"
    r"|laboratory\s+work"
    r"|project\s+work"
    r"|general\s+instructions?"
    r"|instructions?"
    r")\b",
    re.IGNORECASE,
)
_SYLLABUS_SKIP_REST_RE = re.compile(
    r"^(?:text\s*books?|reference\s+books?|recommended\s+(?:reading|books?)|required\s+reading|"
    r"suggested\s+reading|further\s+reading|reading\s+list|web\s+resources|online\s+resources)\b",
    re.IGNORECASE,
)
_SYLLABUS_LINE_NOISE_RES = (
    re.compile(r"^(?:page|pg\.?)\s*\d+(?:\s*(?:of|/)\s*\d+)?$", re.IGNORECASE),
    re.compile(r"^(?:[-–—(]\s*)?\d{1,3}(?:\s*[-–—)])?$"),
    re.compile(r"^\d{1,3}\s*(?:of|/)\s*\d{1,3}$"),
    re.compile(r"^(?:semester|year|batch|session|term)\b.{0,30}$", re.IGNORECASE),
    re.compile(r"^(?:max(?:imum)?|min(?:imum)?)\s*(?:marks|credits?)\b", re.IGNORECASE),
    re.compile(r"^(?:total|grand\s+total)\b.*\d", re.IGNORECASE),
    re.compile(r"^\d+(?:\.\d+)?\s*(?:credits?|marks?|hours?|hrs?|periods?|weeks?|days?)\b", re.IGNORECASE),
    re.compile(r"^(?:theory|practical|tutorial|lab|laboratory|internal|external)\s*[:\-–]?\s*\d+", re.IGNORECASE),
    re.compile(r"^(?:l\s*[-–:]\s*t\s*[-–:]\s*p|\d+\s*[-–]\s*\d+\s*[-–]\s*\d+)\b", re.IGNORECASE),
    re.compile(r"^[A-Z]{2,6}\s*[-–]?\s*\d{2,4}[A-Z]?$"),
    re.compile(r"^(?:e-?mail|phone|mobile|contact)\s*[:\-]", re.IGNORECASE),
    re.compile(r"^[\w.+-]+@[\w.-]+\.\w+$"),
    re.compile(r"^(?:note|notes)\s*[:\-]", re.IGNORECASE),
    re.compile(r"^academic\s+year\b", re.IGNORECASE),
    re.compile(r"^(?:program(?:me)?|branch|specialization|discipline|course|subject|paper)\s*[:\-]", re.IGNORECASE),
    re.compile(r"^(?:name\s+of\s+the\s+(?:course|program(?:me)?)|course\s+name)\b", re.IGNORECASE),
    re.compile(
        r"^(?:b\.?\s*sc|b\.?\s*a|b\.?\s*com|b\.?\s*tech|bca|mca|m\.?\s*sc|m\.?\s*a|mba|"
        r"ph\.?\s*d|b\.?\s*ed|m\.?\s*ed)\b",
        re.IGNORECASE,
    ),
)
_SYLLABUS_METADATA_RE = re.compile(
    r"^(?:pace mode|current level|deadline pressure|confidence level|weak areas|workflow mode|"
    r"target outcome|career family|career toolkit|career outcome|plan topics)\s*:",
    re.IGNORECASE,
)
_SYLLABUS_OBJECTIVE_RE = re.compile(
    r"\b(?:students?\s+will|learners?\s+will|the\s+student|this\s+course|the\s+course|"
    r"upon\s+completion|by\s+the\s+end\s+of|aims?\s+to|ability\s+to|enable\s+students?|"
    r"develop\s+an\s+understanding|introduce\s+students?|familiarize\s+students?|"
    r"provide\s+students?)\b",
    re.IGNORECASE,
)
_SYLLABUS_OBJECTIVE_START_RE = re.compile(
    r"^(?:understand|explain|describe|discuss|identify|apply|analy[sz]e|evaluate|demonstrate|"
    r"develop)\s+(?:the|how|why|various|different|basic|key|major)\b",
    re.IGNORECASE,
)
_SYLLABUS_GENERIC_TOPICS = {
    "introduction", "intro", "overview", "basics", "fundamentals", "general",
    "miscellaneous", "others", "practical", "practicals", "theory", "lab", "labs",
    "laboratory", "project", "projects", "assignment", "assignments", "seminar",
    "workshop", "tutorial", "tutorials", "revision", "examination", "examinations",
    "test", "tests", "quiz", "quizzes", "note", "notes", "references", "textbooks",
    "syllabus", "contents", "topics", "unit", "units", "module", "modules",
    "chapter", "chapters", "part", "parts", "data", "information",
}


def _clean_syllabus_topic(raw):
    text = (raw or "").strip(" \t-*•–—,;:")
    text = re.sub(
        r"\(\s*(?:[A-Z]{2,6}[\s-]?\d{2,4}[A-Z]?|elective\s*[- ]?\d+)\s*\)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:unit|module|chapter|week|topic|section|part|paper)\s*(?:no\.?)?\s*[-–—:.]?\s*"
        r"(?:\d{1,2}|[ivxlcdm]{1,6}|[a-z])\b\s*[:\-–—.]*\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\(?(?:\d+(?:\.\d+)*|[ivxlcdm]+|[a-z])[\).:\-–]\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-–—.")
    return text


def _split_syllabus_parts(text):
    if ";" not in text and "," not in text:
        return [text]
    parts = []
    buffer = []
    depth = 0
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(depth - 1, 0)
        if depth == 0 and char in ";,":
            parts.append("".join(buffer))
            buffer = []
            continue
        buffer.append(char)
    parts.append("".join(buffer))
    cleaned = [re.sub(r"\s+", " ", part).strip(" .;:-") for part in parts]
    cleaned = [part for part in cleaned if part]
    if len(cleaned) <= 1:
        return [text]
    if all(len(part.split()) == 1 for part in cleaned) and " and " not in text.lower() and "&" not in text:
        return [text]
    return cleaned


def _is_syllabus_noise_line(line):
    if any(pattern.match(line) for pattern in _SYLLABUS_LINE_NOISE_RES):
        return True
    if len(line.split()) <= 8 and re.search(
        r"\b(?:university|college|institute|department|school\s+of|faculty\s+of)\b",
        line,
        re.IGNORECASE,
    ):
        return True
    return False


def _extract_topics_from_text(text):
    return _extract_topics_with_stats(text)[0]


def _extract_topics_with_stats(text):
    """Extract real syllabus topics while discarding administrative noise.

    Sections such as course objectives, outcomes, credits, textbooks, and
    references are skipped until the next unit/module heading. Inline lists are
    split on commas and semicolons outside parentheses, and generic headings
    like "Unit 1" or "Course Contents" never become topics.
    """
    stats = {"raw_lines": 0, "noise_lines": 0, "topics": 0}
    if not text:
        return [], stats

    lines = []
    for chunk in str(text).replace("\r", "\n").split("\n"):
        line = chunk.replace("\u00a0", " ")
        line = re.sub(r"^\s*[•▪◦‣·●○–—>›*-]+\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    stats["raw_lines"] = len(lines)

    candidates = []
    seen = set()
    noise_count = 0
    in_admin_section = False
    admin_line_count = 0
    skip_rest = False

    def push(item):
        cleaned = _clean_syllabus_topic(item)
        cleaned = re.sub(r"^(?:and|&|including|such as|e\.g\.?|i\.e\.?|etc\.?)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+(?:etc\.?|and|or)$", "", cleaned, flags=re.IGNORECASE)
        if not cleaned:
            return False
        if not re.search(r"[A-Za-z]{2}", cleaned):
            return False
        lower = cleaned.lower()
        if lower in _SYLLABUS_GENERIC_TOPICS:
            return False
        if _SYLLABUS_OBJECTIVE_RE.search(cleaned) or _SYLLABUS_OBJECTIVE_START_RE.match(cleaned):
            return False
        words = cleaned.split()
        if len(words) > 12 or len(cleaned) > 110:
            return False
        digits = sum(1 for char in cleaned if char.isdigit())
        if digits and digits / max(len(cleaned), 1) > 0.3:
            return False
        key = re.sub(r"[^a-z0-9]+", " ", lower).strip()
        if not key or key in seen:
            return False
        seen.add(key)
        candidates.append(cleaned)
        return True

    def push_line(content):
        accepted = False
        for part in _split_syllabus_parts(content):
            if push(part):
                accepted = True
        return accepted

    for line in lines:
        if _SYLLABUS_METADATA_RE.match(line) or _is_syllabus_noise_line(line):
            noise_count += 1
            continue

        if _SYLLABUS_SKIP_REST_RE.match(line):
            skip_rest = True
            noise_count += 1
            continue
        if skip_rest:
            noise_count += 1
            continue

        is_module = bool(_SYLLABUS_MODULE_HEADING_RE.match(line))
        is_contents = bool(_SYLLABUS_CONTENTS_RE.match(line))

        if _SYLLABUS_ADMIN_HEADING_RE.match(line) and not is_module:
            in_admin_section = True
            admin_line_count = 0
            noise_count += 1
            continue

        if is_module or is_contents:
            in_admin_section = False
            admin_line_count = 0
            if is_contents or _SYLLABUS_MODULE_ONLY_RE.match(line):
                noise_count += 1
                continue
            if not push_line(_clean_syllabus_topic(line)):
                noise_count += 1
            continue

        if in_admin_section:
            admin_line_count += 1
            if admin_line_count <= 22:
                noise_count += 1
                continue
            in_admin_section = False

        content = _clean_syllabus_topic(line)
        if ":" in content:
            left, right = content.split(":", 1)
            if right.strip() and len(left.split()) <= 4 and re.search(r"[A-Za-z]", right):
                content = right.strip()
        if not push_line(content):
            noise_count += 1

    stats["noise_lines"] = noise_count
    stats["topics"] = len(candidates)
    return candidates[:80], stats



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
    if not current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
        return None
    try:
        timeout = current_app.config.get("REQUEST_TIMEOUT_SECONDS", 8)
        response = _request_session().get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.json()
    except Exception:
        return None
    return None


def _safe_get_text(url, headers=None, params=None):
    if not current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
        return None
    try:
        timeout = current_app.config.get("REQUEST_TIMEOUT_SECONDS", 8)
        response = _request_session().get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.text
    except Exception:
        return None
    return None


def _classify_career_family(title):
    key = _normalize(title or "")
    for alias, family in CAREER_FAMILY_ALIASES:
        if alias in key:
            return family
    return "general"


def _dedupe_items(items):
    seen = set()
    cleaned = []
    for item in items:
        text = re.sub(r"\s+", " ", (item or "")).strip()
        key = _normalize(text)
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _build_career_plan(role_title, source_text="", level="beginner", target_outcome=""):
    role = (role_title or "").strip() or "Career Path"
    family_key = _classify_career_family(role)
    family = CAREER_FAMILIES[family_key]

    def fill(items):
        return [item.format(role=role, family=family["label"]) for item in items]

    topics = fill(family["topics"])
    projects = fill(family["projects"])
    assignments = fill(family["assignments"])

    level_key = _normalize(level)
    level_focus = {
        "beginner": f"{role} foundations and vocabulary",
        "intermediate": f"{role} applied practice with real scenarios",
        "advanced": f"{role} advanced patterns and leadership decisions",
    }.get(level_key)
    if level_focus:
        topics.insert(0, level_focus)

    if target_outcome:
        projects.append(f"Outcome proof: {target_outcome}")

    if family["tools"]:
        assignments.append(f"Set up and practice your core toolkit: {', '.join(family['tools'])}")

    topics.extend(_extract_topics_from_text(source_text))
    return {
        "role": role,
        "family": family_key,
        "family_label": family["label"],
        "topics": _dedupe_items(topics)[:14],
        "projects": _dedupe_items(projects)[:5],
        "assignments": _dedupe_items(assignments)[:6],
        "tools": family["tools"],
        "outcome": family["outcome"],
    }


def _supabase_client():
    url = current_app.config.get("SUPABASE_URL")
    key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


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
    if "assignment" in topic.lower():
        base += 1.0
    if "capstone" in topic.lower():
        base += 3.0
    return round(base + extra, 1)


def _resource_score(provider):
    scores = {
        "wikipedia": 0.8,
        "crossref": 0.9,
        "github": 0.7,
        "openalex": 0.85,
        "openlibrary": 0.75,
    }
    return scores.get(provider, 0.6)


def _resource_headers():
    return {"User-Agent": current_app.config.get("WIKIPEDIA_USER_AGENT")}


def _wikipedia_resource(topic):
    headers = _resource_headers()
    search_data = _safe_get(
        "https://en.wikipedia.org/w/api.php",
        headers=headers,
        params={
            "action": "opensearch",
            "search": topic,
            "limit": 1,
            "namespace": 0,
            "format": "json",
        },
    )
    title = topic
    if isinstance(search_data, list) and len(search_data) > 1 and search_data[1]:
        title = str(search_data[1][0])
    summary = _safe_get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}",
        headers=headers,
    )
    if not isinstance(summary, dict) or not summary.get("content_urls"):
        return None
    return {
        "provider": "wikipedia",
        "title": summary.get("title", title),
        "url": summary["content_urls"]["desktop"]["page"],
        "summary": summary.get("extract", ""),
        "score": _resource_score("wikipedia"),
    }


def _openalex_resources(topic, headers):
    params = {"search": topic, "per-page": 2}
    mailto = current_app.config.get("OPENALEX_EMAIL")
    if mailto:
        params["mailto"] = mailto
    data = _safe_get("https://api.openalex.org/works", headers=headers, params=params)
    results = data.get("results") if isinstance(data, dict) else None
    resources = []
    for item in (results or [])[:2]:
        if not isinstance(item, dict):
            continue
        url = item.get("doi") or (
            (item.get("primary_location") or {}).get("landing_page_url")
        )
        title = item.get("display_name") or topic
        if not url:
            continue
        year = item.get("publication_year")
        resources.append({
            "provider": "openalex",
            "title": str(title)[:220],
            "url": str(url),
            "summary": f"Open-access research reference{f' ({year})' if year else ''}",
            "score": _resource_score("openalex"),
        })
    return resources


def _openlibrary_resources(topic, headers):
    data = _safe_get(
        "https://openlibrary.org/search.json",
        headers=headers,
        params={
            "q": topic,
            "limit": 2,
            "fields": "title,key,author_name,first_publish_year",
        },
    )
    docs = data.get("docs") if isinstance(data, dict) else None
    resources = []
    for item in (docs or [])[:2]:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        authors = item.get("author_name") or []
        year = item.get("first_publish_year")
        detail = ", ".join(filter(None, [authors[0] if authors else None, str(year) if year else None]))
        resources.append({
            "provider": "openlibrary",
            "title": str(item.get("title") or topic)[:220],
            "url": f"https://openlibrary.org{item['key']}",
            "summary": f"Free library book{f' · {detail}' if detail else ''}",
            "score": _resource_score("openlibrary"),
        })
    return resources


def _url_looks_dead(url):
    if not current_app.config.get("RESOURCE_VERIFY_URLS", True):
        return False
    try:
        timeout = min(4, current_app.config.get("REQUEST_TIMEOUT_SECONDS", 8))
        response = _request_session().head(url, allow_redirects=True, timeout=timeout)
        return response.status_code in {404, 410}
    except Exception:
        # A blocked or slow HEAD request is not proof that the link is dead.
        return False


def _dedupe_resources(resources, limit=6):
    seen = set()
    kept = []
    for item in resources:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        if _url_looks_dead(url):
            continue
        seen.add(url)
        kept.append(item)
        if len(kept) >= limit:
            break
    return kept


def _fetch_resources_for_topic(topic):
    if not current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
        return []

    headers = _resource_headers()
    resources = []

    wiki = _wikipedia_resource(topic)
    if wiki:
        resources.append(wiki)

    crossref_params = {"query.title": topic, "rows": 2}
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

    resources.extend(_openalex_resources(topic, headers))
    resources.extend(_openlibrary_resources(topic, headers))

    github_headers = {"Accept": "application/vnd.github+json", "User-Agent": headers["User-Agent"]}
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

    limit = max(int(current_app.config.get("RESOURCE_MAX_ITEMS", 6) or 6), 1)
    return _dedupe_resources(resources, limit=limit)


def _schedule_items(items, start_date, timeline_weeks, hours_per_week, study_days_per_week,
                   pace_mode="steady", plan_days=None, hours_per_day=None):
    """Place sequential tasks on real study days at the user's daily capacity.

    The due dates fan out across the whole requested window instead of
    finishing early, so a 60-day plan actually stretches over 60 days.
    If the requested window cannot hold the work, the plan is extended to
    the first date where it fits rather than silently overloading days.
    """
    tasks = []
    if not items:
        items = ["Define milestones", "Gather resources", "Start learning", "Build a mini project"]

    study_days_per_week = _safe_int(study_days_per_week, 5, 1, 7)
    pace_mode = _normalize_pace_mode(pace_mode)
    pace_multiplier = {
        "burnout_safe": 1.15,
        "steady": 1.0,
        "sprint": 0.85,
    }[pace_mode]

    estimated_hours = [_estimate_hours(item) for item in items]
    total_hours = round(sum(estimated_hours), 1) or 1.0

    if hours_per_day is None:
        hours_per_day = (hours_per_week or 6) / study_days_per_week
    hours_per_day = _safe_float(hours_per_day, 2.0, 0.5, 16.0)

    if plan_days and plan_days > 0:
        total_days = max(int(plan_days), 1)
    elif timeline_weeks and timeline_weeks > 0:
        total_days = max(timeline_weeks * 7, 7)
    else:
        required_study_days = math.ceil((total_hours * pace_multiplier) / hours_per_day)
        required_weeks = math.ceil(required_study_days / study_days_per_week)
        total_days = max(required_weeks * 7, 7)

    dates = _study_dates(start_date, total_days, study_days_per_week)
    capacity = len(dates) * hours_per_day
    while capacity + 0.01 < total_hours:
        total_days += 7
        dates = _study_dates(start_date, total_days, study_days_per_week)
        capacity = len(dates) * hours_per_day

    cursor_hours = 0.0
    last_index = 0
    for idx, item in enumerate(items):
        cursor_hours += estimated_hours[idx]
        fraction = min(cursor_hours / total_hours, 1.0)
        day_index = int(round(fraction * (len(dates) - 1)))
        day_index = max(day_index, last_index)
        last_index = day_index
        tasks.append({
            "title": item,
            "order_index": idx + 1,
            "due_date": dates[day_index],
            "difficulty": _estimate_difficulty(item),
            "estimated_hours": estimated_hours[idx],
        })

    return tasks, total_hours, dates[-1]


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
        plan_days=roadmap.plan_days,
        hours_per_day=roadmap.hours_per_day,
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
        month_start = _utc_now().replace(tzinfo=None) - timedelta(days=30)
        previous_start = _utc_now().replace(tzinfo=None) - timedelta(days=60)
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


def _build_momentum_status(roadmaps, tasks=None, checkins=None, next_task=None):
    """Derive a live title, badges, and a motivating message from real progress."""
    roadmaps = list(roadmaps or [])
    today = _utc_today()
    if not roadmaps:
        return {
            "title": "Starting Line",
            "tone": "positive",
            "score": 0,
            "message": "Every roadmap starts with one small step. Create your first plan and we will turn the goal into daily actions.",
            "done": 0,
            "total": 0,
            "overdue": 0,
            "streak": 0,
            "badges": [],
            "next_badge": None,
            "days_since_checkin": None,
        }

    roadmap_ids = [item.id for item in roadmaps]
    if tasks is None:
        tasks = Task.query.filter(Task.roadmap_id.in_(roadmap_ids)).all()
    task_list = list(tasks)
    if checkins is None:
        checkins = Checkin.query.filter(Checkin.roadmap_id.in_(roadmap_ids)).all() if _has_table("checkin") else []

    total = len(task_list)
    done_tasks = [task for task in task_list if task.status == "done"]
    done = len(done_tasks)
    overdue = len([task for task in task_list if task.status != "done" and task.due_date and task.due_date < today])
    on_time = len([task for task in done_tasks if not task.due_date or not task.completed_at or task.completed_at.date() <= task.due_date])
    project_tasks = [task for task in task_list if task.title.startswith("Project:")]
    completed_projects = len([task for task in project_tasks if task.status == "done"])
    completion = done / total if total else 0.0
    on_time_ratio = on_time / done if done else 0.0
    streak = max([int(roadmap.streak or 0) for roadmap in roadmaps] or [0])

    checkin_dates = [item.checkin_date for item in checkins if item.checkin_date]
    checkin_dates.extend(roadmap.last_checkin_date for roadmap in roadmaps if roadmap.last_checkin_date)
    last_checkin = max(checkin_dates) if checkin_dates else None
    days_since_checkin = max((today - last_checkin).days, 0) if last_checkin else None
    recent_checkins = len({day for day in checkin_dates if 0 <= (today - day).days <= 7})
    consistency = (min(streak / 7, 1.0) * 0.5) + (min(recent_checkins / 3, 1.0) * 0.5)

    score = round(completion * 55 + on_time_ratio * 25 + consistency * 20)
    score = max(0, min(100, score - min(overdue * 6, 30)))

    start_dates = [roadmap.start_date for roadmap in roadmaps if roadmap.start_date]
    plan_age = max((today - min(start_dates)).days, 0) if start_dates else 0
    stale = days_since_checkin is not None and days_since_checkin >= 7
    silent_start = total > 0 and done == 0 and plan_age >= 7

    if total and done >= total:
        title, tone = "Roadmap Finisher", "positive"
    elif overdue >= 5 or (overdue >= 2 and stale) or (silent_start and plan_age >= 10):
        title, tone = "Momentum at Risk", "danger"
    elif overdue >= 1 or stale or silent_start:
        title, tone = "Catching Up", "warning"
    elif score >= 75:
        title, tone = "Momentum Architect", "positive"
    elif score >= 55:
        title, tone = "Momentum Builder", "positive"
    elif score >= 35:
        title, tone = "Steady Climber", "positive"
    elif done > 0:
        title, tone = "Momentum Starter", "positive"
    else:
        title, tone = "Fresh Start", "positive"

    badge_specs = [
        ("First Step", "Complete your first task", done >= 1, done, 1),
        ("Five Wins", "Complete five tasks", done >= 5, done, 5),
        ("Ten Down", "Complete ten tasks", done >= 10, done, 10),
        ("Streak Starter", "Keep a 3-day study streak", streak >= 3, streak, 3),
    ]
    if project_tasks:
        badge_specs.append(("Project Shipper", "Finish your first project", completed_projects >= 1, completed_projects, 1))
    if total:
        badge_specs.append(("Halfway Hero", "Reach 50% plan completion", completion >= 0.5, round(completion * 100), 50))
    badge_specs.append(("Consistency Keeper", "Keep a 7-day study streak", streak >= 7, streak, 7))
    if project_tasks:
        badge_specs.append(("Portfolio Proof", "Finish every project in the plan", completed_projects >= len(project_tasks), completed_projects, len(project_tasks)))
    if total:
        badge_specs.append(("Roadmap Finisher", "Complete every task in the plan", done >= total, done, total))

    badges = [
        {"name": name, "detail": detail, "tone": "positive"}
        for name, detail, earned, _, _ in badge_specs if earned
    ]

    delay_badges = []
    if overdue >= 5:
        delay_badges.append({"name": "Overdue Stack", "detail": f"{overdue} tasks are past due. Clear the smallest one first.", "tone": "danger"})
    elif overdue >= 1:
        delay_badges.append({"name": "Delay Alert", "detail": f"{overdue} task(s) are past due. One focused session restores control.", "tone": "warning"})
    if stale:
        delay_badges.append({"name": "Re-Entry Needed", "detail": f"No check-in for {days_since_checkin} days. A 25-minute session restarts momentum.", "tone": "warning"})
    if silent_start and plan_age >= 7:
        delay_badges.append({"name": "Still at the Start", "detail": "The plan has not moved yet. Complete one task to break the freeze.", "tone": "danger"})
    badges.extend(delay_badges)

    next_badge = None
    for name, detail, earned, value, target in badge_specs:
        if not earned:
            next_badge = {
                "name": name,
                "detail": detail,
                "value": value,
                "target": target,
                "progress": round(min(value / target, 1.0) * 100) if target else 0,
            }
            break

    next_title = next_task.title if next_task else None
    if title == "Momentum at Risk":
        message = f"Some tasks slipped, but this is recoverable. Clear one small step{f' — {next_title}' if next_title else ''} to take the pressure down."
    elif tone == "warning":
        message = f"You are still in motion. A short focus block{f' on {next_title}' if next_title else ''} puts the plan back under control."
    elif total and done >= total:
        message = "Every task in this plan is complete. Capture the proof, update your resume, and celebrate the win."
    elif streak >= 3:
        message = f"You are on a {streak}-day streak. {next_title + ' is' if next_title else 'The next task is'} the next win waiting for you."
    elif done > 0:
        message = f"Progress is real: {done} of {total} tasks done. Keep the next step small and finish it today."
    elif total:
        message = f"One finished task changes how this plan feels. Start with {next_title or 'the first task'} today."
    else:
        message = "This plan is ready. Open it and choose your first step."

    return {
        "title": title,
        "tone": tone,
        "score": score,
        "message": message,
        "done": done,
        "total": total,
        "overdue": overdue,
        "streak": streak,
        "badges": badges,
        "next_badge": next_badge,
        "days_since_checkin": days_since_checkin,
    }


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
    week_start = _utc_now().replace(tzinfo=None) - timedelta(days=7)
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
    period_start = _utc_now().replace(tzinfo=None) - timedelta(days=30)
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


def _base_task_topic(task_title):
    cleaned = re.sub(r"^(Project:\s*|Revision Sprint:\s*|Weak-area recovery:\s*)", "", task_title or "", flags=re.IGNORECASE)
    return cleaned.strip()


def _build_revision_engine(roadmap, tasks):
    today = _utc_today()
    revision_queue = []
    revision_tasks = [task for task in tasks if "revision" in _normalize(task.title)]
    done_revision = [task for task in revision_tasks if task.status == "done"]

    for task in tasks:
        if task.status != "done":
            if "revision" in _normalize(task.title) and task.due_date and task.due_date <= today + timedelta(days=3):
                revision_queue.append({
                    "title": task.title,
                    "reason": "This revision block is coming up soon and should stay protected.",
                    "urgency": "soon",
                })
            continue
        if not task.completed_at:
            continue
        days_since = (today - task.completed_at.date()).days
        if days_since in {1, 3, 7, 14}:
            revision_queue.append({
                "title": f"Revise {_base_task_topic(task.title)}",
                "reason": f"Spaced repetition checkpoint for day {days_since}.",
                "urgency": "due" if days_since in {3, 7} else "light",
            })

    days_left = (roadmap.target_date - today).days
    pre_exam_mode = days_left <= 21
    effectiveness = round((len(done_revision) / max(len(revision_tasks), 1)) * 100) if revision_tasks else 0
    return {
        "headline": "Pre-exam revision mode" if pre_exam_mode else "Rolling revision queue",
        "detail": "The next three weeks should prioritize high-yield recall, short tests, and clean review loops." if pre_exam_mode else "Revise before forgetting, not only when panic starts.",
        "queue": revision_queue[:6],
        "effectiveness": effectiveness,
        "pre_exam_mode": pre_exam_mode,
    }


def _build_accountability_loop(roadmap, tasks):
    today = _utc_today()
    recent_checkins = []
    if _has_table("checkin"):
        recent_checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).order_by(Checkin.created_at.desc()).limit(7).all()
    days_since = (today - roadmap.last_checkin_date).days if roadmap.last_checkin_date else None
    weekly_minutes = sum(item.minutes or 0 for item in recent_checkins)
    open_tasks = [task for task in tasks if task.status != "done"]
    reflection_prompt = "What is the one thing that made progress feel heavier than it should have this week?"
    if open_tasks and open_tasks[0].difficulty == "hard":
        reflection_prompt = "Did the current hard task need a smaller first step instead of more pressure?"
    return {
        "headline": "Re-entry support" if days_since is not None and days_since >= 3 else "Accountability loop",
        "detail": "Come back through one 25-minute session, one easy win, and one honest check-in." if days_since is not None and days_since >= 3 else "Small weekly reflections and confidence checks make the roadmap adapt faster.",
        "weekly_minutes": weekly_minutes,
        "days_since": days_since,
        "reflection_prompt": reflection_prompt,
        "confidence_prompt": "Are you confident or just busy this week?",
        "load_prompt": "Did the workload feel manageable, heavy, or overloaded?",
    }


def _build_career_outcomes(roadmap, tasks):
    if roadmap.roadmap_type != "career":
        return None
    project_tasks = [task for task in tasks if task.title.startswith("Project:")]
    assignment_tasks = [task for task in tasks if task.title.startswith("Assignment:")]
    proof_tasks = [task for task in tasks if any(marker in _normalize(task.title) for marker in ["portfolio", "resume", "interview", "proof", "job-ready", "case study"])]
    completed_projects = len([task for task in project_tasks if task.status == "done"])
    completed_assignments = len([task for task in assignment_tasks if task.status == "done"])
    completed_proof = len([task for task in proof_tasks if task.status == "done"])
    portfolio_meter = round((completed_projects / max(len(project_tasks), 1)) * 100) if project_tasks else 0
    readiness = round(((completed_projects * 0.4) + (completed_assignments * 0.2) + (completed_proof * 0.4)) / max(len(project_tasks) + len(assignment_tasks) + len(proof_tasks), 1) * 100)
    family_label = _extract_metadata_value(roadmap.source_text, "Career Family", "Professional path")
    toolkit = [item.strip() for item in _extract_metadata_value(roadmap.source_text, "Career Toolkit", "").split(",") if item.strip()]
    outcome = _extract_metadata_value(roadmap.source_text, "Career Outcome", "")
    return {
        "family_label": family_label,
        "toolkit": toolkit,
        "outcome": outcome,
        "portfolio_meter": portfolio_meter,
        "job_readiness": readiness,
        "project_submission": [task for task in project_tasks[:4]],
        "assignment_submission": [task for task in assignment_tasks[:6]],
        "proof_artifacts": [task for task in proof_tasks[:4]],
        "interview_flow": [
            "Complete one project and capture the challenge, solution, and result.",
            "Turn finished work into a resume bullet with a measurable outcome.",
            "Practice explaining one hard task as an interview story.",
        ],
    }


def _build_upsc_mode_details(roadmap, tasks, tests, attempt_history, quiz_results):
    if roadmap.roadmap_type != "upsc":
        return None
    optional_subject = _extract_optional_subject_from_source_text(roadmap.source_text)
    completed_tests = [test for test in tests if test.status == "completed"]
    avg_test_score = round(sum((test.score or 0) for test in completed_tests) / max(len(completed_tests), 1), 1) if completed_tests else 0
    answer_reviews = []
    question_map = {}
    if attempt_history and _has_table("question"):
        question_ids = [item.question_id for item in attempt_history]
        question_map = {item.id: item for item in Question.query.filter(Question.id.in_(question_ids)).all()}
    for item in attempt_history[:5]:
        question = question_map.get(item.question_id)
        answer_reviews.append({
            "topic": question.topic if question and question.topic else question.subject if question and question.subject else "UPSC practice",
            "score": item.score,
            "note": item.notes or "No review note yet.",
        })
    current_affairs = [task.title for task in tasks if "current affairs" in _normalize(task.title)][:4]
    return {
        "optional_subject": optional_subject or "Not selected yet",
        "completed_tests": len(completed_tests),
        "planned_tests": len([test for test in tests if test.status == "planned"]),
        "avg_test_score": avg_test_score,
        "answer_reviews": answer_reviews,
        "current_affairs": current_affairs or ["Issue-based current affairs mapping", "Daily current affairs notes and weekly revision"],
    }


def _build_analytics_snapshot(roadmap, tasks, attempts, quiz_results):
    checkins = []
    if _has_table("checkin"):
        checkins = Checkin.query.filter_by(roadmap_id=roadmap.id).all()
    week_minutes = {}
    for item in checkins:
        week_key = item.checkin_date - timedelta(days=item.checkin_date.weekday())
        week_minutes.setdefault(week_key, 0)
        week_minutes[week_key] += item.minutes or 0
    sorted_weeks = sorted(week_minutes.items())
    trend = "Rising" if len(sorted_weeks) >= 2 and sorted_weeks[-1][1] >= sorted_weeks[-2][1] else "Uneven"

    strongest_topic = None
    weakest_topic = None
    if attempts:
        topic_scores = {}
        for attempt in attempts.values():
            question = getattr(attempt, "question", None)
            topic = (question.topic if question and question.topic else question.subject if question and question.subject else "General practice")
            topic_scores.setdefault(topic, []).append(attempt.score)
        if topic_scores:
            ranked = sorted(((topic, sum(scores) / len(scores)) for topic, scores in topic_scores.items()), key=lambda item: item[1], reverse=True)
            strongest_topic = ranked[0][0]
            weakest_topic = ranked[-1][0]

    if not strongest_topic:
        completed = [task for task in tasks if task.status == "done"]
        strongest_topic = _base_task_topic(completed[0].title) if completed else "Still forming"
    if not weakest_topic:
        overdue = [task for task in tasks if task.status != "done" and task.due_date and task.due_date < _utc_today()]
        weakest_topic = _base_task_topic(overdue[0].title) if overdue else "No critical weak pocket"

    best_day = None
    if checkins:
        day_totals = {}
        for item in checkins:
            day_name = item.checkin_date.strftime("%A")
            day_totals.setdefault(day_name, 0)
            day_totals[day_name] += item.minutes or 0
        best_day = max(day_totals.items(), key=lambda pair: pair[1])[0]

    revision_tasks = [task for task in tasks if "revision" in _normalize(task.title)]
    revision_effectiveness = round((len([task for task in revision_tasks if task.status == "done"]) / max(len(revision_tasks), 1)) * 100) if revision_tasks else 0
    delayed = [task for task in tasks if task.status != "done" and task.due_date and task.due_date < _utc_today()]
    delay_pattern = f"{len(delayed)} overdue task(s), with {delayed[0].difficulty if delayed else 'no'} dominant delay pattern."
    quiz_trend = round(sum((item.correct / max(item.total_questions, 1)) for item in quiz_results) / len(quiz_results) * 100) if quiz_results else 0
    return {
        "trend": trend,
        "strongest_topic": strongest_topic,
        "weakest_topic": weakest_topic,
        "best_day": best_day or "Not enough data yet",
        "delay_pattern": delay_pattern,
        "revision_effectiveness": revision_effectiveness,
        "quiz_trend": quiz_trend,
    }


def _build_public_examples():
    return [
        {"title": "Semester rescue", "detail": "Messy syllabus became a clean week-by-week plan with revision buffers and assessment checkpoints."},
        {"title": "Career launch path", "detail": "Role learning now ends in portfolio proof, resume bullets, and interview-ready stories."},
        {"title": "UPSC mission system", "detail": "Stage-separated prep with PYQ work, answer-review history, and current-affairs structure."},
    ]


def _build_case_studies():
    return [
        {"title": "Before", "detail": "Users start with overwhelm, vague effort, and no reliable next step."},
        {"title": "After", "detail": "They leave with a daily task, revision queue, weekly assessment, and visible proof of progress."},
        {"title": "Why it matters", "detail": "The product stops being a roadmap generator and becomes a completion system."},
    ]


def _build_weekly_focus_topics(tasks):
    today = _utc_today()
    week_end = today + timedelta(days=7)
    topics = []
    for task in tasks:
        if task.status == "done":
            continue
        if task.due_date and task.due_date > week_end:
            continue
        topic = _base_task_topic(task.title)
        if not topic:
            continue
        if any(item["topic"] == topic for item in topics):
            continue
        timeline_hint = "Due this week" if task.due_date else "Flexible this week"
        if task.due_date and task.due_date < today:
            timeline_hint = "Overdue priority"
        topics.append({
            "topic": topic,
            "due_date": task.due_date,
            "difficulty": task.difficulty or "medium",
            "timeline_hint": timeline_hint,
            "is_revision": "revision" in _normalize(task.title),
        })
    return topics[:8]


def _question_variants(topic, roadmap_type, timeline_hint, is_revision):
    base_topic = topic
    if roadmap_type == "career":
        return [
            {
                "question": f"For {base_topic}, which action best proves employable progress this week?",
                "answer": "Ship one concrete artifact and explain outcomes",
                "options": [
                    "Ship one concrete artifact and explain outcomes",
                    "Keep consuming tutorials without output",
                    "Delay all proof until end of roadmap",
                    "Only rename tasks as done without evidence",
                ],
            },
            {
                "question": f"{base_topic} is in focus ({timeline_hint}). What is the best interview-readiness move?",
                "answer": "Create one STAR-style explanation from this topic's work",
                "options": [
                    "Create one STAR-style explanation from this topic's work",
                    "Avoid reflecting on what you built",
                    "Skip measurable resume bullet drafting",
                    "Add new tools before completing current topic",
                ],
            },
        ]
    if roadmap_type == "upsc":
        return [
            {
                "question": f"Weekly UPSC assessment for {base_topic}: what is the highest-yield next step?",
                "answer": "Attempt a timed answer, review mistakes, and revise weak dimensions",
                "options": [
                    "Attempt a timed answer, review mistakes, and revise weak dimensions",
                    "Only read notes and skip answer writing",
                    "Ignore PYQs for this topic this week",
                    "Collect extra sources without testing retention",
                ],
            },
            {
                "question": f"For {base_topic} ({timeline_hint}), which choice best supports prelims+mains balance?",
                "answer": "Do one objective drill plus one short structured written response",
                "options": [
                    "Do one objective drill plus one short structured written response",
                    "Practice only one format forever",
                    "Avoid revision because the schedule already includes it",
                    "Skip performance review after test attempts",
                ],
            },
        ]
    revision_phrase = "revise-before-forgetting" if is_revision else "progress-check"
    return [
        {
            "question": f"{base_topic} is marked for {revision_phrase} ({timeline_hint}). Which move best improves retention?",
            "answer": "Solve one application and record one mistake pattern",
            "options": [
                "Solve one application and record one mistake pattern",
                "Re-read headings without retrieval practice",
                "Postpone all revision to final week",
                "Mark complete without checking understanding",
            ],
        },
        {
            "question": f"For {base_topic}, what is the best weekly self-assessment method?",
            "answer": "Use a short quiz plus one written explanation in your own words",
            "options": [
                "Use a short quiz plus one written explanation in your own words",
                "Only watch another long video",
                "Skip checks because timeline already exists",
                "Move to next topic without feedback loop",
            ],
        },
    ]


def _generate_contextual_questions(topic_context, amount, roadmap_type="syllabus"):
    question_bank = []
    if not topic_context:
        topic_context = [{"topic": "Core review", "timeline_hint": "This week", "is_revision": False}]

    for item in topic_context:
        topic = item["topic"]
        variants = _question_variants(
            topic,
            roadmap_type,
            item.get("timeline_hint", "This week"),
            bool(item.get("is_revision")),
        )
        for variant in variants:
            options = variant["options"][:]
            random.shuffle(options)
            question_bank.append({
                "question": variant["question"],
                "options": options,
                "answer": variant["answer"],
                "category": topic,
                "source": "Roadmap weekly context",
            })
            if len(question_bank) >= amount:
                return question_bank[:amount]
    return question_bank[:amount]


def _focus_topic_context(roadmap, tasks, mode):
    if mode == "weekly":
        weekly = _build_weekly_focus_topics(tasks)
        if weekly:
            return weekly
    return [
        {"topic": _base_task_topic(task.title), "timeline_hint": "This week", "is_revision": False}
        for task in tasks
        if _base_task_topic(task.title)
    ]


def _build_assessment_questions(roadmap, tasks, amount=10, difficulty="medium", mode="standard",
                                focus_topics=None):
    context = _focus_topic_context(roadmap, tasks, mode)
    if focus_topics:
        context = [
            {"topic": topic, "timeline_hint": "Weak area", "is_revision": True}
            for topic in focus_topics
        ]
    topics = [item["topic"] for item in context][:8]

    if roadmap.roadmap_type != "upsc":
        contextual = _generate_contextual_questions(
            context or [{"topic": "Core review", "timeline_hint": "This week", "is_revision": False}],
            amount,
            roadmap.roadmap_type,
        )
        return contextual[:amount], topics

    stats = ensure_pyq_synced()
    if stats["prelims_total"] < 1:
        return [], topics

    subjects = subject_keywords_for_topics([item["topic"] for item in context])
    subject_focus = subjects or ["All verified UPSC prelims subjects"]
    if mode == "mock":
        subjects = None
    questions = prelims_questions(
        amount=amount,
        subjects=subjects,
        topics=focus_topics,
        exclude_texts=[],
        spread_years=(mode == "mock"),
        include_unverified=(mode == "open"),
        archive_only=(mode == "open"),
    )
    for item in questions:
        letter = item.get("correct", "")
        item["answer"] = item["options"]["abcd".index(letter)] if letter in "abcd" and len(item["options"]) == 4 else ""
        item["category"] = f"{item.get('subject', 'General Studies')} · {item.get('year', '')}".strip(" ·")
        item["source"] = item.get("source") or "UPSC previous-year paper"
    return questions, subject_focus


def _persist_quiz_questions(roadmap, questions, difficulty, mode):
    persisted = []
    for item in questions:
        options = item.get("options") or []
        correct = str(item.get("correct") or "").strip().lower()
        if correct not in {"a", "b", "c", "d"}:
            answer_text = (item.get("answer") or "").strip()
            correct = "abcd"[options.index(answer_text)] if answer_text in options else "a"
        row = QuizQuestion(
            question_text=(item.get("question") or "").strip(),
            options_json=json.dumps(options),
            correct_answer=correct,
            category=(item.get("category") or "")[:180] or None,
            source=(item.get("source") or "")[:80] or None,
            source_url=(item.get("source_url") or "")[:600] or None,
            difficulty=difficulty,
            mode=mode,
            user_id=session["user_id"],
            roadmap_id=roadmap.id,
        )
        db.session.add(row)
        db.session.flush()
        persisted.append(
            {
                "id": row.id,
                "question": row.question_text,
                "options": options,
                "category": row.category,
                "source": row.source,
                "source_url": row.source_url,
                "year": item.get("year"),
            }
        )

    protected = set()
    if _has_quiz_question_attempt_schema():
        protected = {
            row.question_id
            for row in QuizQuestionAttempt.query.join(
                QuizResult, QuizResult.id == QuizQuestionAttempt.quiz_result_id
            ).filter(QuizResult.user_id == session["user_id"]).limit(2000).all()
        }
    stale_query = QuizQuestion.query.filter(
        QuizQuestion.user_id == session["user_id"],
        QuizQuestion.roadmap_id == roadmap.id,
        QuizQuestion.id.not_in([item["id"] for item in persisted]),
    )
    if protected:
        stale_query = stale_query.filter(QuizQuestion.id.not_in(protected))
    for row in stale_query.order_by(QuizQuestion.created_at.asc()).limit(500).all():
        db.session.delete(row)
    db.session.commit()
    return persisted


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


def _build_tasks(roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week,
                 study_days_per_week, pace_mode="steady", source_text="", plan_days=None,
                 hours_per_day=None, assignments=None):
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

    if roadmap_type == "career":
        for assignment in assignments or []:
            all_items.append(f"Assignment: {assignment}")

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

    return _schedule_items(
        all_items, start_date, timeline_weeks, hours_per_week, study_days_per_week,
        pace_mode, plan_days=plan_days, hours_per_day=hours_per_day,
    )


_NON_TOPIC_TASK_PREFIXES = ("Project: ", "Assignment: ", "Revision Sprint: ", "Weak-area recovery: ")
_NON_TOPIC_TASK_TITLES = {
    "portfolio readiness review", "resume bullet drafting", "interview question bank",
    "job-ready proof artifact", "answer writing review framework",
    "revision calendar before mocks", "issue-based current affairs mapping",
    "high-yield revision drill", "time-boxed self-test and review",
}


def _topic_key(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _clean_topic_list(items):
    cleaned = []
    seen = set()
    for item in items or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip(" ,;:-–—")
        if not text or len(text) < 3 or len(text) > 140:
            continue
        if not re.search(r"[A-Za-z]", text):
            continue
        key = _topic_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= 80:
            break
    return cleaned


def _roadmap_topics(roadmap, tasks):
    stored = _extract_metadata_value(roadmap.source_text, "Plan Topics", "")
    if stored:
        try:
            parsed = json.loads(stored)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            topics = _clean_topic_list([str(item) for item in parsed])
            if topics:
                return topics

    topics = []
    for task in tasks:
        title = (task.title or "").strip()
        if any(title.startswith(prefix) for prefix in _NON_TOPIC_TASK_PREFIXES):
            continue
        if title.lower() in _NON_TOPIC_TASK_TITLES:
            continue
        topics.append(title)
    return _clean_topic_list(topics)


def _rebuild_unfinished_tasks(roadmap, topics, tasks):
    """Rebuild unfinished work around edited topics without touching history."""
    done_tasks = [task for task in tasks if task.status == "done"]
    unfinished = [task for task in tasks if task.status != "done"]
    done_keys = {_topic_key(task.title) for task in done_tasks}

    projects = []
    assignments = []
    for task in tasks:
        title = task.title or ""
        if title.startswith("Project: "):
            projects.append(title[len("Project: "):])
        elif title.startswith("Assignment: "):
            assignments.append(title[len("Assignment: "):])
    projects = _dedupe_items(projects)
    assignments = _dedupe_items(assignments)

    for task in unfinished:
        db.session.delete(task)

    today = _utc_today()
    remaining_days = max((roadmap.target_date - today).days + 1, 7)
    specs, _, computed_end = _build_tasks(
        roadmap.roadmap_type,
        topics,
        projects,
        today,
        0,
        roadmap.hours_per_week or 6,
        roadmap.study_days_per_week or 5,
        _extract_pace_mode_from_source_text(roadmap.source_text),
        roadmap.source_text,
        plan_days=remaining_days,
        hours_per_day=roadmap.hours_per_day or 2,
        assignments=assignments,
    )

    for index, task in enumerate(done_tasks, start=1):
        task.order_index = index

    optional_subject = _extract_metadata_value(roadmap.source_text, "Optional Subject", "")
    created = []
    seen = set(done_keys)
    order = len(done_tasks)
    for spec in specs:
        key = _topic_key(spec["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        order += 1
        task = Task(
            title=spec["title"],
            order_index=order,
            due_date=spec["due_date"],
            difficulty=spec["difficulty"],
            estimated_hours=spec["estimated_hours"],
            roadmap_id=roadmap.id,
        )
        if roadmap.roadmap_type == "upsc":
            for resource in _upsc_resources_for_task(task.title, optional_subject):
                task.resources.append(Resource(
                    provider=resource["provider"],
                    title=resource["title"],
                    url=resource["url"],
                    summary=resource.get("use_case", "Curated UPSC resource"),
                    score=0.95,
                ))
        db.session.add(task)
        created.append(task)

    completed_hours = sum(
        task.actual_hours if task.actual_hours and task.actual_hours > 0 else (task.estimated_hours or 0.0)
        for task in done_tasks
    )
    remaining_hours = sum(task.estimated_hours or 0.0 for task in created)
    roadmap.completed_tasks = len(done_tasks)
    roadmap.total_tasks = len(done_tasks) + len(created)
    roadmap.total_hours_est = round(completed_hours + remaining_hours, 1)
    if created:
        roadmap.target_date = max((task.due_date for task in created if task.due_date), default=computed_end)
    elif done_tasks:
        roadmap.target_date = max(
            (task.completed_at.date() for task in done_tasks if task.completed_at),
            default=today,
        )
    else:
        roadmap.target_date = computed_end
    roadmap.plan_days = max((roadmap.target_date - roadmap.start_date).days + 1, 1)
    roadmap.source_text = _replace_metadata_line(
        roadmap.source_text, "Plan Topics", json.dumps(topics, ensure_ascii=False)
    )
    db.session.commit()
    return len(created), len(unfinished)


def _background_sync_pyq(app):
    with app.app_context():
        try:
            ensure_pyq_synced()
        except Exception:
            current_app.logger.exception("Background PYQ sync failed")


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
            pending = [
                (task.id, task.title.replace("Project: ", ""))
                for task in tasks
                if not task.resources
            ]
            # Release the read transaction before the slow network calls. On
            # SQLite an open read transaction blocks writers, including quiz
            # generation in another request.
            db.session.remove()
            for task_id, title in pending:
                resources = _fetch_resources_for_topic(title)
                task = db.session.get(Task, task_id)
                if task is None:
                    continue
                for res in resources:
                    db.session.add(Resource(
                        provider=res["provider"],
                        title=res["title"],
                        url=res["url"],
                        summary=res.get("summary", ""),
                        score=res.get("score", 0.0),
                        last_checked_at=_utc_now().replace(tzinfo=None),
                        task_id=task.id
                    ))
                task.last_resource_refresh = _utc_now().replace(tzinfo=None)
                db.session.commit()
            roadmap = db.session.get(Roadmap, roadmap_id)
            if roadmap is not None:
                roadmap.resource_fetch_status = "done"
                roadmap.resource_fetch_completed_at = _utc_now().replace(tzinfo=None)
                db.session.commit()
        except Exception:
            db.session.rollback()
            try:
                roadmap = db.session.get(Roadmap, roadmap_id)
                if roadmap is not None:
                    roadmap.resource_fetch_status = "failed"
                    db.session.commit()
            except Exception:
                db.session.rollback()
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


def _build_plan_summary(roadmap, tasks):
    study_days_per_week = _safe_int(roadmap.study_days_per_week, 5, 1, 7)
    hours_per_day = _safe_float(
        roadmap.hours_per_day or (roadmap.hours_per_week or 6) / study_days_per_week,
        2, 0.5, 16,
    )
    requested_days = _safe_int(roadmap.plan_days, 0, 0, 3650)
    actual_days = max((roadmap.target_date - roadmap.start_date).days + 1, 1)
    dates = _study_dates(roadmap.start_date, actual_days, study_days_per_week)
    capacity = round(len(dates) * hours_per_day, 1)
    scheduled = round(sum(task.estimated_hours or 0 for task in tasks), 1)
    remaining = round(sum(task.estimated_hours or 0 for task in tasks if task.status != "done"), 1)
    completed_hours = round(scheduled - remaining, 1)
    utilization = scheduled / capacity if capacity else 0
    daily_average = scheduled / len(dates) if dates else 0
    buffer_hours = round(capacity - scheduled, 1)

    if utilization > 1.05:
        status, tone = "Overloaded", "danger"
        message = "The requested window is too short. The plan was extended; add days or hours per day for breathing room."
    elif utilization > 0.85:
        status, tone = "Tight", "warn"
        message = "This is workable but leaves little slack. Protect the study days and keep rest days free."
    elif utilization < 0.5:
        status, tone = "Light", "good"
        message = "There is spare capacity. Use it for PYQs, mock analysis, and revision instead of adding new topics."
    else:
        status, tone = "Balanced", "good"
        message = "The workload fits your available study time with a sensible buffer."

    coverage = round((completed_hours / scheduled) * 100, 1) if scheduled else 0
    return {
        "requested_days": requested_days or actual_days,
        "actual_days": actual_days,
        "study_days": len(dates),
        "study_days_per_week": study_days_per_week,
        "hours_per_day": hours_per_day,
        "hours_per_week": round(hours_per_day * study_days_per_week, 1),
        "capacity_hours": capacity,
        "scheduled_hours": scheduled,
        "remaining_hours": remaining,
        "completed_hours": completed_hours,
        "buffer_hours": buffer_hours,
        "daily_average": round(daily_average, 1),
        "utilization": round(utilization * 100, 1),
        "coverage": coverage,
        "status": status,
        "tone": tone,
        "message": message,
        "finish_date": roadmap.target_date,
    }


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
    return render_template('home.html', demo_cards=demo_cards, public_examples=_build_public_examples(), case_studies=_build_case_studies())


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
    momentum = _build_momentum_status(roadmaps, next_task=active_next)
    return render_template('dashboard.html', user=user, roadmaps=roadmaps, active_roadmap=active_roadmap, active_next=active_next, recent_improvements=RECENT_IMPROVEMENTS, dashboard_insights=dashboard_insights, momentum=momentum)


@dashboard_bp.route('/roadmap/parse-nl', methods=['POST'])
@login_required
@rate_limit(60, 600, scope="roadmap.parse_nl")
def parse_nl_plan():
    payload = request.get_json(silent=True) or request.form
    text = (payload.get('nl_input') or payload.get('text') or '').strip()
    if not text:
        return jsonify({"error": "Describe your plan first.", "understood": False}), 400
    return jsonify(parse_plan_text(text[:3000]))


@dashboard_bp.route('/roadmap/new', methods=['GET', 'POST'])
@login_required
@rate_limit(20, 600, scope="roadmap.create")
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
            plan_days = _safe_int(request.form.get('plan_days', request.form.get('total_days', 0)) or 0, 0, 0, 730)
            timeline_weeks = _safe_int(request.form.get('timeline_weeks', 0) or 0, 0, 0, 104)
            study_days_per_week = _safe_int(request.form.get('study_days_per_week', 5) or 5, 5, 1, 7)

            nl_input = request.form.get('nl_input', '').strip()
            nl_plan = parse_plan_text(nl_input) if nl_input else {}
            if nl_plan.get('understood'):
                if (
                    nl_plan.get('roadmap_type') == 'career'
                    and roadmap_type == 'syllabus'
                    and request.form.get('nl_type_touched') != '1'
                ):
                    roadmap_type = 'career'
                if not title:
                    title = nl_plan.get('title', '')
                if plan_days == 0 and nl_plan.get('plan_days'):
                    plan_days = nl_plan['plan_days']
                if timeline_weeks == 0 and nl_plan.get('timeline_weeks'):
                    timeline_weeks = nl_plan['timeline_weeks']
                if nl_plan.get('study_days_per_week') and request.form.get('study_days_per_week') in (None, '', '5'):
                    study_days_per_week = nl_plan['study_days_per_week']
                if nl_plan.get('current_level') and current_level == 'beginner':
                    current_level = nl_plan['current_level']
                if nl_plan.get('pace_mode') and pace_mode == 'steady':
                    pace_mode = nl_plan['pace_mode']
                if not target_outcome:
                    target_outcome = nl_plan.get('target_outcome', '')
                if not weak_areas_input:
                    weak_areas_input = nl_plan.get('weak_areas', '')

            hours_per_day_raw = request.form.get('hours_per_day')
            if hours_per_day_raw in (None, '', '2') and nl_plan.get('hours_per_day'):
                hours_per_day_raw = str(nl_plan['hours_per_day'])
            if hours_per_day_raw not in (None, ''):
                hours_per_day = _safe_float(hours_per_day_raw, 2, 0.5, 16)
                hours_per_week = max(1, round(hours_per_day * study_days_per_week))
            else:
                hours_per_week = _safe_int(request.form.get('hours_per_week', 6) or 6, 6, 1, 80)
                hours_per_day = _safe_float(hours_per_week / study_days_per_week, 2, 0.5, 16)
            start_date = _safe_date(request.form.get('start_date'))

            raw_text = request.form.get('source_text', '').strip()
            source_text_input = raw_text
            confirmed_topics = request.form.get('confirmed_topics', '').strip()
            uploaded = request.files.get('syllabus_file')
            has_upload = bool(uploaded and uploaded.filename)
            if has_upload:
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

            use_nl_topics = bool(nl_plan.get('understood') and nl_plan.get('topics')) and not source_text_input and not has_upload
            if use_nl_topics and not raw_text:
                raw_text = "\n".join(nl_plan['topics'])

            topics = []
            projects = []
            assignments = []
            extraction_stats = {"raw_lines": 0, "noise_lines": 0, "topics": 0}
            if roadmap_type == "career":
                career_plan = _build_career_plan(title, raw_text, current_level, target_outcome)
                if confirmed_topics:
                    topics = [t.strip() for t in confirmed_topics.splitlines() if t.strip()]
                elif use_nl_topics:
                    topics = _clean_topic_list(nl_plan['topics'])
                    extraction_stats = {
                        "raw_lines": len(nl_plan['topics']),
                        "noise_lines": 0,
                        "topics": len(topics),
                    }
                else:
                    topics = career_plan["topics"]
                projects = career_plan["projects"]
                assignments = career_plan["assignments"]
                title = title or career_plan["role"]
                raw_text = _append_metadata_line(raw_text, "Career Family", career_plan["family_label"])
                raw_text = _append_metadata_line(raw_text, "Career Toolkit", ", ".join(career_plan["tools"]))
                raw_text = _append_metadata_line(raw_text, "Career Outcome", career_plan["outcome"])
            elif confirmed_topics:
                topics = [t.strip() for t in confirmed_topics.splitlines() if t.strip()]
            elif use_nl_topics:
                topics = _clean_topic_list(nl_plan['topics'])
                extraction_stats = {
                    "raw_lines": len(nl_plan['topics']),
                    "noise_lines": 0,
                    "topics": len(topics),
                }
            else:
                topics, extraction_stats = _extract_topics_with_stats(raw_text)

            if roadmap_type == "syllabus" and not confirmed_topics:
                if not topics:
                    flash("Please provide a syllabus text or upload a file with clear topics.")
                    return redirect(url_for('dashboard.create_roadmap'))
                return render_template(
                    "roadmap_preview.html",
                    title=title,
                    roadmap_type=roadmap_type,
                    timeline_weeks=timeline_weeks,
                    plan_days=plan_days,
                    hours_per_week=hours_per_week,
                    hours_per_day=hours_per_day,
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
                    original_topics=topics,
                    filtered_count=extraction_stats["noise_lines"],
                    raw_line_count=extraction_stats["raw_lines"],
                    nl_summary=nl_plan.get('summary', []) if nl_plan.get('understood') else [],
                    nl_notes=nl_plan.get('notes', []) if nl_plan.get('understood') else [],
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
                hours_per_week, study_days_per_week, pace_mode=pace_mode,
                plan_days=plan_days, hours_per_day=hours_per_day, assignments=assignments,
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


@dashboard_bp.route('/roadmap/<int:roadmap_id>/topics', methods=['GET', 'POST'])
@login_required
@rate_limit(30, 600, scope="roadmap.topics")
def edit_topics(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    current_topics = _roadmap_topics(roadmap, tasks)

    if request.method == 'POST':
        topics = _clean_topic_list(request.form.get('confirmed_topics', '').splitlines())
        if not topics:
            flash("Keep at least one topic before saving.")
            return redirect(url_for('dashboard.edit_topics', roadmap_id=roadmap.id))
        if topics == current_topics:
            flash("No topic changes to save.")
            return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
        try:
            added, removed = _rebuild_unfinished_tasks(roadmap, topics, tasks)
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to update roadmap topics")
            flash("We couldn't update those topics right now. Please try again.")
            return redirect(url_for('dashboard.edit_topics', roadmap_id=roadmap.id))
        if roadmap.roadmap_type == "career" and current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
            thread = threading.Thread(
                target=_background_fetch_resources,
                args=(current_app._get_current_object(), roadmap.id),
                daemon=True,
            )
            thread.start()
        flash(
            f"Topics updated: {added} task(s) scheduled and {removed} unfinished task(s) replaced. "
            "Completed tasks were preserved."
        )
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    return render_template(
        'roadmap_topics.html',
        roadmap=roadmap,
        topics="\n".join(current_topics),
        original_topics=current_topics,
        task_count=len(tasks),
        done_count=len([task for task in tasks if task.status == "done"]),
    )


@dashboard_bp.route('/upsc/new', methods=['GET', 'POST'])
@login_required
@rate_limit(20, 600, scope="roadmap.create_upsc")
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
            plan_days = _safe_int(request.form.get('plan_days', request.form.get('total_days', 0)) or 0, 0, 0, 730)
            timeline_weeks = _safe_int(request.form.get('timeline_weeks', 0) or 0, 0, 0, 104)
            study_days_per_week = _safe_int(request.form.get('study_days_per_week', 6) or 6, 6, 1, 7)
            hours_per_day_raw = request.form.get('hours_per_day')
            if hours_per_day_raw not in (None, ''):
                hours_per_day = _safe_float(hours_per_day_raw, 3, 0.5, 16)
                hours_per_week = max(1, round(hours_per_day * study_days_per_week))
            else:
                hours_per_week = _safe_int(request.form.get('hours_per_week', 20) or 20, 20, 1, 80)
                hours_per_day = _safe_float(hours_per_week / study_days_per_week, 3, 0.5, 16)
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

            if not confirmed_topics:
                return render_template(
                    "roadmap_preview.html",
                    title=title,
                    roadmap_type="upsc",
                    timeline_weeks=timeline_weeks,
                    plan_days=plan_days,
                    hours_per_week=hours_per_week,
                    hours_per_day=hours_per_day,
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
                hours_per_week, study_days_per_week, upsc_focus, upsc_optional_subject, pace_mode,
                plan_days=plan_days, hours_per_day=hours_per_day,
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
                if _has_mock_test_schedule_schema():
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

            pyq_thread = threading.Thread(
                target=_background_sync_pyq,
                args=(current_app._get_current_object(),),
                daemon=True
            )
            pyq_thread.start()
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
    if _has_mock_test_schedule_schema():
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
    revision_engine = _build_revision_engine(roadmap, tasks)
    accountability_loop = _build_accountability_loop(roadmap, tasks)
    career_outcomes = _build_career_outcomes(roadmap, tasks)
    attempt_history = QuestionAttempt.query.filter_by(user_id=session['user_id']).order_by(QuestionAttempt.attempted_at.desc()).limit(8).all() if roadmap.roadmap_type == "upsc" and _has_table("question_attempt") else []
    upsc_mode = _build_upsc_mode_details(roadmap, tasks, tests, attempt_history, quiz_results)
    analytics_snapshot = _build_analytics_snapshot(roadmap, tasks, attempts, quiz_results)
    resource_groups_map = {task.id: _build_resource_groups(annotated_resources_map.get(task.id, [])) for task in tasks}
    milestones = _build_milestones(roadmap, tasks, tests, done_map, attempts)
    readiness_metrics = _build_readiness_metrics(roadmap, tasks, tests, done_map, attempts, quiz_results)
    plan_summary = _build_plan_summary(roadmap, tasks)
    roadmap_pulse = _build_momentum_status(
        [roadmap],
        tasks=tasks,
        next_task=next((item for item in tasks if item.status != "done"), None),
    )
    return render_template(
        'roadmap_view.html',
        plan_summary=plan_summary,
        roadmap_pulse=roadmap_pulse,
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
        revision_engine=revision_engine,
        accountability_loop=accountability_loop,
        career_outcomes=career_outcomes,
        upsc_mode=upsc_mode,
        analytics_snapshot=analytics_snapshot,
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
    ensure_pyq_synced()
    questions = mains_questions(amount=12)
    attempts = {a.question_id: a for a in QuestionAttempt.query.filter_by(user_id=session['user_id']).all()}
    current_year = _utc_now().year
    years = list(range(current_year - 9, current_year + 1))
    completions = PyqCompletion.query.filter_by(user_id=session['user_id'], roadmap_id=roadmap.id).all()
    done_map = {}
    for c in completions:
        done_map.setdefault(c.exam, []).append(c.year)
    pyq_total = sum(len(items) for items in done_map.values())
    avg_score = round(sum(a.score for a in attempts.values()) / max(len(attempts), 1), 1) if attempts else 0.0
    weak_areas = _build_weak_area_summary(
        Question.query.filter_by(stage="mains", is_public=True).limit(80).all(),
        attempts,
    )
    coverage = coverage_stats()
    practice_coach = _build_practice_coach(pyq_total, avg_score, weak_areas)
    readiness_metrics = _build_readiness_metrics(
        roadmap,
        Task.query.filter_by(roadmap_id=roadmap.id).all(),
        MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).all() if _has_mock_test_schedule_schema() else [],
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
        readiness_metrics=readiness_metrics,
        coverage=coverage,
        is_admin=_is_admin(),
        official_pyq_url=OFFICIAL_PYQ_URL,
        official_answer_key_url=OFFICIAL_ANSWER_KEY_URL,
        pyq_attribution=PYQ_ATTRIBUTION,
    )


UPSC_MATERIALS_EXTRA = [
    {
        "title": "Economic Survey",
        "url": "https://www.indiabudget.gov.in/economicsurvey/",
        "provider": "official",
        "bucket": "Deep study",
        "tags": ["Economy", "Official", "Data"],
        "use_case": "Use the latest survey for economy data, policy direction, and mains-ready examples.",
        "topics": ["economy", "budget", "mains", "interview"],
    },
    {
        "title": "Union Budget Documents",
        "url": "https://www.indiabudget.gov.in",
        "provider": "official",
        "bucket": "Official source",
        "tags": ["Economy", "Budget", "Official"],
        "use_case": "Primary source for budget allocations, schemes, and fiscal policy examples.",
        "topics": ["economy", "budget", "governance", "mains"],
    },
    {
        "title": "Yojana Magazine",
        "url": "https://yojana.gov.in",
        "provider": "official",
        "bucket": "Quick revision",
        "tags": ["Current affairs", "Society", "Mains"],
        "use_case": "Monthly theme-based reading for social issues, schemes, and essay material.",
        "topics": ["society", "governance", "current affairs", "mains", "essay"],
    },
    {
        "title": "Supreme Court of India Judgments",
        "url": "https://main.sci.gov.in/judgments",
        "provider": "official",
        "bucket": "Deep study",
        "tags": ["Polity", "Judiciary", "Official"],
        "use_case": "Use landmark judgments for polity answers, constitutional morality, and governance debates.",
        "topics": ["polity", "constitution", "governance", "mains"],
    },
    {
        "title": "UPSC Model Question and Answer Booklets",
        "url": "https://upsc.gov.in/examination/model-question-and-answer-booklets",
        "provider": "upsc",
        "bucket": "Official source",
        "tags": ["Model answers", "Mains", "Answer writing"],
        "use_case": "See the official answer structure, language, and depth expected in mains.",
        "topics": ["mains", "answer writing", "ethics", "optional"],
    },
    {
        "title": "UPSC Answer Keys",
        "url": OFFICIAL_ANSWER_KEY_URL,
        "provider": "upsc",
        "bucket": "Official source",
        "tags": ["PYQ", "Answer key", "Official"],
        "use_case": "Verify every prelims PYQ answer against the official key before trusting a mock score.",
        "topics": ["prelims", "pyq", "revision"],
    },
]

MAINS_PAPER_SUBJECTS = {
    "GS-I": {"History", "Geography"},
    "GS-II": {"Polity", "International Relations"},
    "GS-III": {"Economy", "Environment", "Science & Technology", "Current Affairs"},
}


def _upsc_mains_papers_for_roadmap(roadmap, tasks):
    papers = []
    source_text = roadmap.source_text or ""
    for label in ("GS Paper I", "GS Paper II", "GS Paper III"):
        if label.lower() in source_text.lower():
            papers.append(label.replace("GS Paper ", "GS-").replace("I", "I"))
    subjects = set(subject_keywords_for_topics([task.title for task in tasks]))
    for paper, mapped in MAINS_PAPER_SUBJECTS.items():
        if subjects & mapped and paper not in papers:
            papers.append(paper)
    return papers or ["GS-I", "GS-II", "GS-III"]


@dashboard_bp.route('/roadmap/<int:roadmap_id>/mains')
@login_required
def mains_practice(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if roadmap.roadmap_type != "upsc":
        flash("Mains practice is part of UPSC missions.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    available_papers = _upsc_mains_papers_for_roadmap(roadmap, tasks)

    selected_paper = request.args.get("paper", "").strip()
    if selected_paper not in {"GS-I", "GS-II", "GS-III"}:
        selected_paper = ""
    ensure_pyq_synced()
    questions = mains_questions(
        amount=6,
        papers=[selected_paper] if selected_paper else available_papers,
    )
    if not questions:
        questions = mains_questions(amount=6)
    attempts = {
        a.question_id: a
        for a in QuestionAttempt.query.filter_by(user_id=session['user_id']).all()
    }
    return render_template(
        "mains.html",
        roadmap=roadmap,
        questions=questions,
        attempts=attempts,
        available_papers=available_papers,
        selected_paper=selected_paper,
        coverage=coverage_stats(),
        official_pyq_url=OFFICIAL_PYQ_URL,
        official_answer_key_url=OFFICIAL_ANSWER_KEY_URL,
        pyq_attribution=PYQ_ATTRIBUTION,
    )


@dashboard_bp.route('/roadmap/<int:roadmap_id>/interview')
@login_required
def interview_prep(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if roadmap.roadmap_type != "upsc":
        flash("Interview practice is part of UPSC missions.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
    profile = {
        "optional_subject": _extract_metadata_value(roadmap.source_text, "Optional Subject", ""),
        "weak_areas": _extract_metadata_value(roadmap.source_text, "Weak Areas", ""),
        "target_outcome": _extract_metadata_value(roadmap.source_text, "Target Outcome", ""),
    }
    prompts = get_interview_set(profile, amount=8)
    return render_template(
        "interview.html",
        roadmap=roadmap,
        prompts=prompts,
        profile=profile,
        official_pyq_url=OFFICIAL_PYQ_URL,
    )


@dashboard_bp.route('/roadmap/<int:roadmap_id>/materials')
@login_required
def materials(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()

    items = []
    seen_urls = set()
    if roadmap.roadmap_type == "upsc":
        for resource in UPSC_CURATED_RESOURCES + UPSC_MATERIALS_EXTRA:
            if resource["url"] in seen_urls:
                continue
            seen_urls.add(resource["url"])
            items.append(dict(resource))

    roadmap_items = []
    for task in tasks:
        for resource in sorted(task.resources, key=lambda r: -(r.score or 0))[:2]:
            if not resource.url or resource.url in seen_urls:
                continue
            seen_urls.add(resource.url)
            roadmap_items.append({
                "title": resource.title,
                "url": resource.url,
                "provider": resource.provider,
                "bucket": "From your roadmap",
                "tags": [task.title[:40], "Task resource"],
                "use_case": resource.summary or f"Added for: {task.title}",
                "topics": [],
            })

    groups = {}
    for item in items + roadmap_items:
        groups.setdefault(item["bucket"], []).append(item)
    return render_template(
        "materials.html",
        roadmap=roadmap,
        groups=groups,
        coverage=coverage_stats(),
        is_admin=_is_admin(),
        official_pyq_url=OFFICIAL_PYQ_URL,
        official_answer_key_url=OFFICIAL_ANSWER_KEY_URL,
        pyq_attribution=PYQ_ATTRIBUTION,
    )


@dashboard_bp.route('/roadmap/<int:roadmap_id>/pyq/sync', methods=['POST'])
@login_required
@rate_limit(3, 300, scope="pyq.sync")
def force_pyq_sync(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if not _is_admin():
        flash("The PYQ cache refresh button is available to the platform admin only.")
        return redirect(url_for('dashboard.practice', roadmap_id=roadmap.id))
    stats = ensure_pyq_synced(force=True, wait=True)
    detail = []
    for key in ("prelims_state", "mains_state"):
        state = stats.get(key) or {}
        if state.get("status") == "failed":
            detail.append(state.get("detail") or f"{key} sync failed")
    if detail:
        flash("PYQ refresh finished with errors: " + " ".join(detail))
    else:
        flash(
            f"PYQ cache refreshed: {stats.get('prelims_total', 0)} prelims and "
            f"{stats.get('mains_total', 0)} mains questions."
        )
    if request.form.get("next") == "materials":
        return redirect(url_for('dashboard.materials', roadmap_id=roadmap.id))
    return redirect(url_for('dashboard.practice', roadmap_id=roadmap.id))


@dashboard_bp.route('/roadmap/<int:roadmap_id>/quiz', methods=['GET'])
@login_required
@rate_limit(60, 60, scope="quiz.generate")
def quiz(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if not (_has_table("quiz_result") and _has_quiz_question_schema()):
        flash("Tests are temporarily unavailable until the database schema is updated.")
        return redirect(url_for('dashboard.dashboard'))

    mode = request.args.get("mode", "standard")
    if mode not in {"standard", "weekly", "pyq", "mock", "open"}:
        mode = "standard"
    if roadmap.roadmap_type != "upsc" and mode in {"pyq", "mock", "open"}:
        mode = "standard"

    if mode == "mock":
        amount = 100
    elif mode == "weekly":
        amount = _safe_int(request.args.get("amount", 10), 10, 5, 20)
    else:
        amount = _safe_int(request.args.get("amount", 10), 10, 5, 50)
    difficulty = request.args.get("difficulty", "medium")
    if difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"

    retest_topics = []
    retest_id = request.args.get("retest", type=int)
    if retest_id and _has_quiz_question_attempt_schema():
        prior = QuizResult.query.filter_by(
            id=retest_id, user_id=session['user_id'], roadmap_id=roadmap.id
        ).first()
        if prior is not None:
            rows = (
                db.session.query(QuizQuestion.category)
                .join(QuizQuestionAttempt, QuizQuestionAttempt.question_id == QuizQuestion.id)
                .filter(
                    QuizQuestionAttempt.quiz_result_id == prior.id,
                    QuizQuestionAttempt.is_correct.is_(False),
                )
                .all()
            )
            for (category,) in rows:
                label = re.split(r"\s+·\s+", category or "", maxsplit=1)[0].strip()
                if label and label not in {"General", "General Studies"} and label not in retest_topics:
                    retest_topics.append(label)
            retest_topics = retest_topics[:8]
            if not retest_topics:
                flash("That attempt had no incorrect answers to build a retest from.")
                return redirect(url_for('dashboard.quiz', roadmap_id=roadmap.id))

    tasks = Task.query.filter_by(roadmap_id=roadmap.id).order_by(Task.order_index.asc()).all()
    pyq_stats = ensure_pyq_synced(wait=True) if roadmap.roadmap_type == "upsc" else None
    raw_questions, focus_topics = _build_assessment_questions(
        roadmap, tasks, amount=amount, difficulty=difficulty, mode=mode,
        focus_topics=retest_topics or None,
    )
    if not raw_questions:
        if roadmap.roadmap_type == "upsc":
            flash("The free PYQ cache is not ready yet. Use the official UPSC links below and retry shortly.")
        else:
            flash("No test questions were available for this roadmap yet. Add more topics and retry.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))

    questions = _persist_quiz_questions(roadmap, raw_questions, difficulty, mode)
    recent_results = QuizResult.query.filter_by(
        user_id=session['user_id'], roadmap_id=roadmap.id
    ).order_by(QuizResult.attempted_at.desc()).limit(5).all()
    duration = 120 if mode == "mock" else 20 if mode == "weekly" else max(10, len(questions) * 2)
    return render_template(
        "quiz.html",
        roadmap=roadmap,
        questions=questions,
        recent_results=recent_results,
        selected_amount=amount,
        selected_difficulty=difficulty,
        mode=mode,
        focus_topics=focus_topics,
        is_retest=bool(retest_topics),
        duration_minutes=duration,
        pyq_stats=pyq_stats,
        official_pyq_url=OFFICIAL_PYQ_URL,
        official_answer_key_url=OFFICIAL_ANSWER_KEY_URL,
        pyq_attribution=PYQ_ATTRIBUTION,
    )


@dashboard_bp.route('/roadmap/<int:roadmap_id>/quiz/submit', methods=['POST'])
@login_required
@rate_limit(30, 60, scope="quiz.submit")
def quiz_submit(roadmap_id):
    roadmap = Roadmap.query.get_or_404(roadmap_id)
    if roadmap.user_id != session['user_id']:
        return redirect(url_for('dashboard.dashboard'))
    if not (_has_table("quiz_result") and _has_quiz_question_schema()):
        flash("Tests are temporarily unavailable until the database schema is updated.")
        return redirect(url_for('dashboard.dashboard'))

    mode = request.form.get("mode", "standard")
    if mode not in {"standard", "weekly", "pyq", "mock", "open"}:
        mode = "standard"

    submitted = []
    for key in request.form:
        if not key.startswith("qid_"):
            continue
        idx = key[4:]
        qid = request.form.get(key, "")
        if qid.isdigit():
            submitted.append((idx, int(qid), request.form.get(f"q_{idx}", "")))

    question_ids = [qid for _, qid, _ in submitted]
    question_map = {
        item.id: item
        for item in QuizQuestion.query.filter(
            QuizQuestion.id.in_(question_ids) if question_ids else False,
            QuizQuestion.user_id == session["user_id"],
            QuizQuestion.roadmap_id == roadmap.id,
        ).all()
    } if question_ids else {}

    correct = 0
    incorrect = 0
    unanswered = 0
    answer_rows = []
    review_items = []
    for idx, qid, selected in submitted:
        row = question_map.get(qid)
        if row is None:
            continue
        try:
            options = json.loads(row.options_json or "[]")
        except (TypeError, ValueError):
            options = []
        selected = selected.strip().lower()
        if selected not in {"a", "b", "c", "d"}:
            unanswered += 1
            is_correct = False
            selected_answer = None
        else:
            is_correct = selected == row.correct_answer
            selected_answer = selected
            if is_correct:
                correct += 1
            else:
                incorrect += 1
        answer_rows.append((row.id, selected_answer, is_correct))
        correct_index = "abcd".find(row.correct_answer)
        review_items.append({
            "question": row.question_text,
            "options": options,
            "selected": selected_answer,
            "correct": row.correct_answer,
            "correct_text": options[correct_index] if 0 <= correct_index < len(options) else row.correct_answer,
            "is_correct": is_correct,
            "category": row.category,
            "source": row.source,
            "source_url": row.source_url,
        })

    total = len(review_items)
    if total == 0:
        flash("That test submission was empty. Please generate a fresh test.")
        return redirect(url_for('dashboard.quiz', roadmap_id=roadmap.id, mode=mode))

    negative_marking = roadmap.roadmap_type == "upsc" and mode != "open"
    score = (correct * 2) - (incorrect * (2 / 3)) if negative_marking else correct
    accuracy = round((correct / total) * 100, 2)
    result = QuizResult(
        total_questions=total,
        correct=correct,
        incorrect=incorrect,
        score=round(score, 2),
        mode=mode,
        user_id=session['user_id'],
        roadmap_id=roadmap.id
    )
    db.session.add(result)
    db.session.flush()
    if _has_quiz_question_attempt_schema():
        for question_id, selected, is_correct in answer_rows:
            db.session.add(
                QuizQuestionAttempt(
                    selected_answer=selected,
                    is_correct=is_correct,
                    quiz_result_id=result.id,
                    question_id=question_id,
                )
            )
    db.session.commit()

    analysis = []
    if total >= 100:
        analysis.append("Full-length mock completed. Review every wrong answer before your next mock.")
    if accuracy >= 75:
        analysis.append("Strong test performance. Keep the rhythm steady and revise weak pockets.")
    elif accuracy >= 50:
        analysis.append("Moderate performance. Revise the missed subjects and retest after consolidation.")
    else:
        analysis.append("This score suggests you should slow down, revise, and retest after consolidating basics.")
    if negative_marking and incorrect > correct:
        analysis.append("Too many risky attempts. Work on elimination and selective answering.")
    if unanswered:
        analysis.append(f"{unanswered} question(s) were left blank. In UPSC prelims, a calculated skip is often better than a guess.")
    if correct < max(total // 2, 4):
        analysis.append("Focus on concept revision before the next test instead of adding too many new topics.")
    weak_topics = []
    for item in review_items:
        if item["is_correct"]:
            continue
        label = re.split(r"\s+·\s+", item.get("category") or "", maxsplit=1)[0].strip()
        if label and label not in {"General", "General Studies"} and label not in weak_topics:
            weak_topics.append(label)
    weak_topics = weak_topics[:8]
    retest_url = None
    if weak_topics:
        retest_url = url_for(
            'dashboard.quiz',
            roadmap_id=roadmap.id,
            mode='open' if mode == 'open' else 'standard',
            amount=max(5, min(total, 20)),
            retest=result.id,
        )
    next_steps = _build_quiz_next_steps(accuracy, result)
    return render_template(
        "quiz_result.html",
        roadmap=roadmap,
        result=result,
        accuracy=accuracy,
        analysis=analysis,
        next_steps=next_steps,
        review_items=review_items,
        unanswered=unanswered,
        negative_marking=negative_marking,
        weak_topics=weak_topics,
        retest_url=retest_url,
        mode=mode,
        official_pyq_url=OFFICIAL_PYQ_URL,
        official_answer_key_url=OFFICIAL_ANSWER_KEY_URL,
        pyq_attribution=PYQ_ATTRIBUTION,
    )


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
    if not _has_mock_test_schedule_schema():
        flash("Mock test scheduling is temporarily unavailable until the database schema is updated.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
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
    if not _has_mock_test_schedule_schema():
        flash("Mock test updates are temporarily unavailable until the database schema is updated.")
        return redirect(url_for('dashboard.view_roadmap', roadmap_id=roadmap.id))
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
            last_checked_at=_utc_now().replace(tzinfo=None),
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
    tests = MockTestSchedule.query.filter_by(roadmap_id=roadmap.id).order_by(MockTestSchedule.scheduled_date.asc()).all() if _has_mock_test_schedule_schema() else []
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

    plan_days = _safe_int(request.form.get('plan_days'), roadmap.plan_days or 0, 0, 730)
    hours_per_day = _safe_float(request.form.get('hours_per_day'), roadmap.hours_per_day or 2, 0.5, 16)
    timeline_weeks = _safe_int(request.form.get('timeline_weeks', 0) or 0, 0, 0, 104)
    roadmap.plan_days = plan_days or None
    roadmap.hours_per_day = hours_per_day
    roadmap.hours_per_week = max(1, round(hours_per_day * _safe_int(roadmap.study_days_per_week, 5, 1, 7)))
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
                     hours_per_week, study_days_per_week, upsc_focus="", upsc_optional_subject="", pace_mode="steady",
                     plan_days=None, hours_per_day=None, assignments=None):
    task_specs, total_hours, computed_end = _build_tasks(
        roadmap_type, topics, projects, start_date, timeline_weeks, hours_per_week,
        study_days_per_week, pace_mode, raw_text,
        plan_days=plan_days, hours_per_day=hours_per_day, assignments=assignments,
    )
    target_date = computed_end
    if hours_per_day is None:
        hours_per_day = _safe_float(hours_per_week / max(study_days_per_week, 1), 2, 0.5, 16)
    plan_days = plan_days or ((target_date - start_date).days + 1)

    stored_source = raw_text or f"UPSC Focus: {upsc_focus}\nOptional Subject: {upsc_optional_subject}"
    stored_source = _replace_metadata_line(stored_source, "Plan Topics", json.dumps(topics, ensure_ascii=False))
    roadmap = Roadmap(
        title=title,
        roadmap_type=roadmap_type,
        source_text=stored_source[:12000],
        start_date=start_date,
        target_date=target_date,
        total_tasks=len(task_specs),
        completed_tasks=0,
        total_hours_est=total_hours,
        hours_per_week=hours_per_week,
        hours_per_day=hours_per_day,
        plan_days=plan_days,
        study_days_per_week=study_days_per_week,
        timezone=current_app.config.get("DEFAULT_TIMEZONE", "Asia/Kolkata"),
        resource_fetch_status="idle",
        user_id=session['user_id']
    )
    db.session.add(roadmap)
    db.session.flush()

    auto_fetch = bool(current_app.config.get("AUTO_FETCH_RESOURCES_ON_CREATE", False))
    if roadmap_type == "career" and current_app.config.get("ENABLE_EXTERNAL_RESOURCES", True):
        auto_fetch = True
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
    owned_task = (
        Task.query.join(Roadmap, Task.roadmap_id == Roadmap.id)
        .filter(
            Task.evidence_path == filename,
            Roadmap.user_id == session["user_id"],
        )
        .first()
    )
    if owned_task is None:
        flash("That attachment is not available.")
        return redirect(url_for('dashboard.dashboard'))

    storage_client = _supabase_client()
    if storage_client and "/" in filename:
        user_prefix = f"{session['user_id']}/"
        if not filename.startswith(user_prefix):
            flash("That attachment is not available.")
            return redirect(url_for('dashboard.dashboard'))
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
