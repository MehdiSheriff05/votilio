from flask import Blueprint

admin_bp = Blueprint('admin', __name__)

from app.admin import access_routes, auth, csv_import, elections, settings, voters  # noqa: E402,F401
from app.access import guard  # noqa: E402

admin_bp.before_request(guard)
