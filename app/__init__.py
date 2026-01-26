from flask import Flask
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from config import Config


db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)
    upload_dir = app.config.get("UPLOAD_FOLDER")
    if upload_dir:
        import os

        os.makedirs(upload_dir, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    from app.utils import format_display_time, active_timezone_label
    app.jinja_env.filters['display_time'] = format_display_time
    @app.context_processor
    def inject_timezone():
        return {"timezone_label": active_timezone_label()}

    from app.admin.routes import admin_bp
    from app.public.routes import public_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.teardown_request
    def cleanup_db_session(exception=None):
        if exception:
            db.session.rollback()
        db.session.remove()

    @app.errorhandler(OperationalError)
    def handle_db_operational_error(error):
        app.logger.error("Database operational error: %s", error, exc_info=True)
        return "Database connection error. Please retry.", 500

    @app.errorhandler(SQLAlchemyError)
    def handle_db_error(error):
        app.logger.error("Database error: %s", error, exc_info=True)
        return "Database error. Please retry.", 500

    @app.shell_context_processor
    def make_shell_context():
        # Expose db and models for quick CLI usage.
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
