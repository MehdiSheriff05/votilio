import os
import re
import uuid
from datetime import timedelta, timezone
from functools import wraps
from typing import Callable, Optional

from flask import current_app, flash, redirect, session, url_for
from jinja2 import Template
from markupsafe import Markup, escape
from PIL import Image
from werkzeug.utils import secure_filename

from app import db
from app.models import AuditLog, AdminUser, SystemSettings


def login_required(view_func: Callable):
    """Decorator that makes sure the admin session exists before continuing."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("admin.login"))
        if not AdminUser.query.get(admin_id):
            session.pop("admin_id", None)
            session.pop("is_super_admin", None)
            session.pop("admin_name", None)
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
    if admin_id and not AdminUser.query.get(admin_id):
        admin_id = None
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
            quality = int(current_app.config.get("IMAGE_QUALITY", 80))
            max_bytes = int(current_app.config.get("IMAGE_MAX_BYTES", 100 * 1024))
            fmt = img.format or ext.upper()
            fmt = 'JPEG' if fmt.upper() in ('JPG', 'JPEG') else fmt.upper()

            def _save_image(target_fmt: str, target_quality: int) -> None:
                if target_fmt == 'JPEG':
                    img_converted = img.convert("RGB")
                    img_converted.save(path, format='JPEG', optimize=True, quality=target_quality)
                elif target_fmt == 'WEBP':
                    img.save(path, format='WEBP', optimize=True, quality=target_quality)
                elif target_fmt == 'PNG':
                    img.save(path, format='PNG', optimize=True)
                else:
                    img.save(path, format=target_fmt, optimize=True)

            _save_image(fmt, quality)
            if os.path.getsize(path) > max_bytes:
                # Enforce hard size cap by re-encoding as JPEG with decreasing quality.
                target_quality = min(quality, 85)
                while target_quality >= 30:
                    _save_image('JPEG', target_quality)
                    if os.path.getsize(path) <= max_bytes:
                        break
                    target_quality -= 10
    except Exception:
        # fallback to raw save if PIL choked
        file_storage.stream.seek(0)
        file_storage.save(path)
    relative_path = os.path.relpath(path, os.path.join(current_app.root_path, 'static'))
    return relative_path.replace("\\", "/")


def render_email_template(template_string: str, context: dict) -> str:
    """Quick helper to render our editable email templates with Jinja placeholders."""
    return Template(template_string).render(**context)


def active_timezone_label() -> str:
    """Returns the current default timezone name (System Settings overrides config)."""
    fallback = current_app.config.get("DISPLAY_TIMEZONE", "UTC")
    try:
        settings = SystemSettings.query.first()
        if settings and settings.timezone_name:
            return settings.timezone_name
    except Exception:
        # DB might not be initialized yet during early CLI usage.
        pass
    return fallback


def _zoneinfo_for(label: str):
    """Best effort loader that returns a timezone offset for GMT/UTC labels."""
    offset = _timezone_offset_from_label(label)
    if offset is not None:
        return timezone(offset)
    return None


def _timezone_offset_from_label(label: str) -> Optional[timedelta]:
    """Parses GMT/UTC style offsets like GMT+4 or UTC-05:30."""
    if not label:
        return None
    cleaned = label.strip().upper().replace('UTC', '').replace('GMT', '')
    match = re.match(r'^([+-])\s*(\d{1,2})(?::(\d{2}))?$', cleaned)
    if not match:
        return None
    sign = 1 if match.group(1) == '+' else -1
    hours = int(match.group(2))
    minutes = int(match.group(3)) if match.group(3) else 0
    return timedelta(hours=sign * hours, minutes=sign * minutes)


def format_display_time(dt, placeholder: str = "Not available", render_html: bool = True) -> str:
    """Human friendly label with configured GMT offset, or placeholder when dt missing."""
    tz_label = active_timezone_label()
    if not dt:
        return placeholder if not render_html else escape(placeholder)
    tzinfo = _zoneinfo_for(tz_label)
    base_dt = dt
    if dt.tzinfo is None:
        base_dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = base_dt.astimezone(timezone.utc)
    local_dt = utc_dt.astimezone(tzinfo) if tzinfo else utc_dt
    rendered = f"{local_dt.strftime('%Y-%m-%d %H:%M')} ({tz_label})"
    if not render_html:
        return rendered
    return Markup(escape(rendered))
