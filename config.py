import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
    PREFERRED_URL_SCHEME = os.environ.get("PREFERRED_URL_SCHEME", "https")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@db:5432/votilio",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", 1800)),
        "pool_size": int(os.environ.get("DB_POOL_SIZE", 5)),
        "max_overflow": int(os.environ.get("DB_POOL_MAX_OVERFLOW", 10)),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", 30)),
        "connect_args": {
            "keepalives": 1,
            "keepalives_idle": int(os.environ.get("DB_KEEPALIVE_IDLE", 30)),
            "keepalives_interval": int(os.environ.get("DB_KEEPALIVE_INTERVAL", 10)),
            "keepalives_count": int(os.environ.get("DB_KEEPALIVE_COUNT", 5)),
        },
    }
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 1025))
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    MAIL_SENDER = os.environ.get("MAIL_SENDER", "no-reply@votilio.local")
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(BASE_DIR, "app", "static", "uploads"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 10 * 1024 * 1024))
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    IMAGE_MAX_WIDTH = int(os.environ.get("IMAGE_MAX_WIDTH", 800))
    IMAGE_QUALITY = int(os.environ.get("IMAGE_QUALITY", 80))
    IMAGE_MAX_BYTES = int(os.environ.get("IMAGE_MAX_BYTES", 100 * 1024))
    SEND_EMAIL_ASYNC = os.environ.get("SEND_EMAIL_ASYNC", "true").lower() == "true"
    DISPLAY_TIMEZONE = os.environ.get("DISPLAY_TIMEZONE", "GMT+4")
    USE_PROXY_FIX = os.environ.get("USE_PROXY_FIX", "true").lower() == "true"


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
