import os

from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    if app.config.get("APP_ENV") == "production" and not app.config.get("TESTING"):
        secret = app.config.get("SECRET_KEY") or ""
        if len(secret) < 32:
            raise RuntimeError(
                "FLASK_SECRET_KEY must be set to at least 32 characters in production. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )

    proxies = int(app.config.get("TRUSTED_PROXY_COUNT") or 0)
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    from app.utils import format_display_time, format_short_time, active_timezone_label, brand_style

    app.jinja_env.filters["display_time"] = format_display_time
    app.jinja_env.filters["short_time"] = format_short_time
    app.jinja_env.globals["brand_style"] = brand_style

    import time
    asset_version = str(int(time.time()))

    @app.context_processor
    def inject_globals():
        from flask import request, session
        ctx = {"timezone_label": active_timezone_label(), "asset_v": asset_version}
        if request.blueprint == "admin" and session.get("admin_id"):
            from app.access import visible_elections
            ctx["palette_elections"] = [{"id": e.id, "name": e.name} for e in visible_elections().limit(50).all()]
        return ctx

    from app.admin import admin_bp
    from app.public.routes import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.get("/healthz")
    @csrf.exempt
    @limiter.exempt
    def healthz():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            return jsonify(status="error"), 503
        return jsonify(status="ok")

    from flask import render_template, request
    from flask_wtf.csrf import CSRFError

    csp = ("default-src 'self'; img-src 'self' data: https: http:; style-src 'self' 'unsafe-inline'; "
           "script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
           "base-uri 'self'; form-action 'self'; object-src 'none'")

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if response.mimetype == "text/html":
            response.headers.setdefault("Content-Security-Policy", csp)
            response.headers.setdefault("Cache-Control", "no-store")
        if request.is_secure and not app.config.get("TESTING"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    def _error(status, title, message):
        if request.headers.get("X-Requested-With") == "fetch" or request.is_json:
            return jsonify(ok=False, message=message), status
        return render_template("error.html", status=status, title=title, message=message), status

    @app.errorhandler(CSRFError)
    def csrf_error(_):
        return _error(400, "Session expired", "This page was open for too long. Refresh it and try again.")

    @app.errorhandler(404)
    def not_found(_):
        return _error(404, "Page not found", "That page doesn't exist or has moved.")

    @app.errorhandler(413)
    def too_large(_):
        return _error(413, "File too large", "That upload is bigger than the allowed size.")

    @app.errorhandler(429)
    def rate_limited(_):
        return _error(429, "Too many attempts", "Slow down a little and try again in a minute.")

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        return _error(500, "Something went wrong", "We hit an unexpected error. Please try again.")

    from app.cli import register_cli

    register_cli(app)

    @app.shell_context_processor
    def make_shell_context():
        from app import models

        return {
            "db": db,
            "AdminUser": models.AdminUser,
            "Election": models.Election,
            "Position": models.Position,
            "Candidate": models.Candidate,
            "VoterInvitation": models.VoterInvitation,
            "Vote": models.Vote,
            "AuditLog": models.AuditLog,
            "SystemSettings": models.SystemSettings,
        }

    return app
