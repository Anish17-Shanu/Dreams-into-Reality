import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "track_secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # SQLite needs a busy timeout so a short background write does not fail a
    # concurrent request with "database is locked". Postgres ignores this.
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"connect_args": {"timeout": 30, "check_same_thread": False}}
        if SQLALCHEMY_DATABASE_URI.startswith("sqlite")
        else {}
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    # HTTPS-only cookies by default only in production; local HTTP dev needs them off.
    APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
    IS_PRODUCTION = APP_ENV in {"production", "prod"}
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true" if IS_PRODUCTION else "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "dir_session")
    TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "true" if IS_PRODUCTION else "false").lower() == "true"
    RATELIMIT_ENABLED = os.getenv("RATELIMIT_ENABLED", "true").lower() == "true"
    ORIGIN_CHECK_ENABLED = os.getenv("ORIGIN_CHECK_ENABLED", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.getenv("SESSION_DAYS", "14")))
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads"))
    MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH_MB", "20"))
    MAX_CONTENT_LENGTH = MAX_CONTENT_LENGTH_MB * 1024 * 1024
    ENABLE_EXTERNAL_RESOURCES = os.getenv("ENABLE_EXTERNAL_RESOURCES", "true").lower() == "true"
    WIKIPEDIA_USER_AGENT = os.getenv("WIKIPEDIA_USER_AGENT", "DreamsIntoReality/1.0 (contact@example.com)")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "")
    OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "")
    RESOURCE_REFRESH_DAYS = int(os.getenv("RESOURCE_REFRESH_DAYS", "7"))
    REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "8"))
    PYQ_SYNC_ENABLED = os.getenv("PYQ_SYNC_ENABLED", "true").lower() == "true"
    PYQ_REFRESH_DAYS = int(os.getenv("PYQ_REFRESH_DAYS", "7"))
    PYQ_REQUEST_TIMEOUT_SECONDS = int(os.getenv("PYQ_REQUEST_TIMEOUT_SECONDS", "20"))
    PYQ_USER_AGENT = os.getenv(
        "PYQ_USER_AGENT",
        "DreamsIntoReality/1.0 (free UPSC previous-year-question cache)",
    )
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "evidence")
    SIGNED_URL_EXPIRES_SECONDS = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "600"))
    AUTO_FETCH_RESOURCES_ON_CREATE = os.getenv("AUTO_FETCH_RESOURCES_ON_CREATE", "false").lower() == "true"
    AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true"
    ADMIN_EMAILS = [
        item.strip().lower()
        for item in os.getenv("ADMIN_EMAILS", "").split(",")
        if item.strip()
    ]
    PYQ_SEED_ENABLED = os.getenv("PYQ_SEED_ENABLED", "true").lower() == "true"
    PYQ_SEED_PATH = os.getenv(
        "PYQ_SEED_PATH",
        os.path.join(BASE_DIR, "pyq", "seed", "upsc_bank.json.gz"),
    )
    RESOURCE_VERIFY_URLS = os.getenv("RESOURCE_VERIFY_URLS", "true").lower() == "true"
    RESOURCE_MAX_ITEMS = int(os.getenv("RESOURCE_MAX_ITEMS", "6"))
    DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
