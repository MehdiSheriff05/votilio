import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.environ.get("APP_ENV", "production").lower()
IS_PRODUCTION = APP_ENV == "production"


class Config:
    APP_ENV = APP_ENV
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://votilio:votilio@db:5432/votilio",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", IS_PRODUCTION)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_HOURS", 12)))
    PREFERRED_URL_SCHEME = "https" if IS_PRODUCTION else "http"
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", 1 if IS_PRODUCTION else 0))

    # Email. The provider and credentials may also be set from the admin UI;
    # values provided here take priority so secrets can live in the environment.
    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "").lower()
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls").lower()
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_SENDER = os.environ.get("MAIL_SENDER", "no-reply@votilio.local")
    MAIL_SENDER_NAME = os.environ.get("MAIL_SENDER_NAME", "")
    EMAIL_CHUNK_SIZE = int(os.environ.get("EMAIL_CHUNK_SIZE", 25))

    # Must stay inside app/static so photo URLs resolve; mount a volume here in Docker.
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 4 * 1024 * 1024))
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    IMAGE_MAX_WIDTH = int(os.environ.get("IMAGE_MAX_WIDTH", 800))
    IMAGE_QUALITY = int(os.environ.get("IMAGE_QUALITY", 80))
    DISPLAY_TIMEZONE = os.environ.get("DISPLAY_TIMEZONE", "GMT+4")

    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_ENABLED = True
    MAX_IMPORT_ROWS = int(os.environ.get("MAX_IMPORT_ROWS", 20000))

    BOOTSTRAP_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class DevelopmentConfig(Config):
    DEBUG = True


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key-not-for-production-0123456789"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SESSION_COOKIE_SECURE = False
    PREFERRED_URL_SCHEME = "http"
    WTF_CSRF_ENABLED = True
    RATELIMIT_ENABLED = False
    TRUSTED_PROXY_COUNT = 0
    SMTP_HOST = ""
