import os
import uuid
from functools import wraps
from typing import Callable, Optional

from flask import current_app, flash, redirect, session, url_for
from jinja2 import Template
from PIL import Image
from werkzeug.utils import secure_filename

from app import db
from app.models import AuditLog, AdminUser


def login_required(view_func: Callable):
    """Decorator that makes sure the admin session exists before continuing."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("admin.login"))
        return view_func(*args, **kwargs)

    return wrapped


def super_admin_required(view_func: Callable):
    """Decorator gate for any view that only super admins should touch."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("admin.login"))
        admin = AdminUser.query.get(admin_id)
        if not admin or not admin.is_super_admin:
            flash("Super admin access required.", "danger")
            return redirect(url_for("admin.dashboard"))
        return view_func(*args, **kwargs)

    return wrapped


def current_admin_id() -> Optional[int]:
    """Quick helper so other modules do not read the session directly."""
    return session.get("admin_id")


def record_audit(event_type: str, message: str, admin_id: Optional[int] = None,
                 election_id: Optional[int] = None, invitation_id: Optional[int] = None) -> None:
    """Persists a new audit entry while defaulting admin_id from the session."""
    if admin_id is None:
        admin_id = current_admin_id()
    log = AuditLog(
        event_type=event_type,
        message=message,
        admin_id=admin_id,
        election_id=election_id,
        invitation_id=invitation_id,
    )
    db.session.add(log)
    db.session.commit()


def allowed_file(filename: str) -> bool:
    """Validates uploaded filenames against the configured whitelist."""
    if not filename:
        return False
    allowed = current_app.config.get("ALLOWED_IMAGE_EXTENSIONS", set())
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def save_uploaded_image(file_storage) -> Optional[str]:
    """Compresses and stores candidate photos, returning the relative static path."""
    if not file_storage or file_storage.filename == '':
        return None
    if not allowed_file(file_storage.filename):
        return None
    filename = secure_filename(file_storage.filename)
    ext = filename.rsplit('.', 1)[1].lower()
    new_name = f"{uuid.uuid4().hex}.{ext}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    path = os.path.join(upload_folder, new_name)
    file_storage.stream.seek(0)
    try:
        with Image.open(file_storage.stream) as img:
            max_width = current_app.config.get("IMAGE_MAX_WIDTH", 800)
            if img.width > max_width:
                # keeping visuals lightweight prevents ballot pages from feeling sluggish
                ratio = max_width / float(img.width)
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.LANCZOS)
            quality = current_app.config.get("IMAGE_QUALITY", 80)
            fmt = img.format or ext.upper()
            fmt = 'JPEG' if fmt.upper() in ('JPG', 'JPEG') else fmt.upper()
            if fmt == 'JPEG':
                img = img.convert("RGB")
                img.save(path, format='JPEG', optimize=True, quality=quality)
            else:
                if fmt == 'PNG':
                    img.save(path, format='PNG', optimize=True)
                elif fmt == 'WEBP':
                    img.save(path, format='WEBP', optimize=True, quality=quality)
                else:
                    img.save(path, format=fmt, optimize=True)
    except Exception:
        # fallback to raw save if PIL choked
        file_storage.stream.seek(0)
        file_storage.save(path)
    relative_path = os.path.relpath(path, os.path.join(current_app.root_path, 'static'))
    return relative_path.replace("\\", "/")


def render_email_template(template_string: str, context: dict) -> str:
    """Quick helper to render our editable email templates with Jinja placeholders."""
    return Template(template_string).render(**context)


def format_display_time(dt, placeholder: str = "Not available") -> str:
    """Human friendly label with configured timezone, or placeholder when dt missing."""
    tz_label = current_app.config.get("DISPLAY_TIMEZONE", "GMT+4")
    if not dt:
        return f"{placeholder}"
    # we intentionally standardize format so tables across the app match
    return f"{dt.strftime('%Y-%m-%d %H:%M')} ({tz_label})"
