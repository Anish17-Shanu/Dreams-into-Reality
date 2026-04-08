import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "track_secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
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
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
    AI_TOPIC_EXTRACTION_ENABLED = os.getenv("AI_TOPIC_EXTRACTION_ENABLED", "false").lower() == "true"
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "evidence")
    SIGNED_URL_EXPIRES_SECONDS = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "600"))
    AUTO_FETCH_RESOURCES_ON_CREATE = os.getenv("AUTO_FETCH_RESOURCES_ON_CREATE", "false").lower() == "true"
    AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "false").lower() == "true"
    DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
    ESCO_API_BASE = os.getenv("ESCO_API_BASE", "https://ec.europa.eu/esco/api")
