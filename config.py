import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "track_secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///db.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads"))
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
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
    HF_API_KEY = os.getenv("HF_API_KEY", "")
    HF_MODEL = os.getenv("HF_MODEL", "google/flan-t5-large")
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "evidence")
    SIGNED_URL_EXPIRES_SECONDS = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "600"))
