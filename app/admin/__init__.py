from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

from app.admin import auth, csv_import, elections, settings, voters  # noqa: E402,F401
