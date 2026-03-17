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
