import os
import re
import uuid
from datetime import timedelta, timezone
from functools import wraps
from typing import Callable, Optional

from flask import current_app, flash, redirect, request, session, url_for
from jinja2.sandbox import SandboxedEnvironment
from PIL import Image
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from werkzeug.utils import secure_filename

from app import db
from app.models import AuditLog, AdminUser, SystemSettings


def login_required(view_func: Callable):
    """Decorator that makes sure the admin session exists before continuing."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            if request.method == "GET" and request.path.startswith("/admin"):
                return redirect(url_for("admin.login", next=request.full_path.rstrip("?")))
            flash("Your session expired. Please sign in again.", "warning")
            return redirect(url_for("admin.login"))
        return view_func(*args, **kwargs)

    return wrapped


def super_admin_required(view_func: Callable):
    """Decorator gate for any view that only super admins should touch."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            return redirect(url_for("admin.login"))
        admin = db.session.get(AdminUser, admin_id)
        if not admin or not admin.is_super_admin:
            flash("That area is for super admins only.", "danger")
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
    """Validates, resizes and stores a candidate photo; returns the path relative to static/, or None."""
    if not file_storage or file_storage.filename == '':
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = secure_filename(file_storage.filename).rsplit('.', 1)[-1].lower()
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    file_storage.stream.seek(0)
    try:
        with Image.open(file_storage.stream) as img:
            img.load()
            fmt = (img.format or '').upper()
            if fmt not in ('JPEG', 'PNG', 'GIF', 'WEBP'):
                return None
            max_width = current_app.config.get("IMAGE_MAX_WIDTH", 800)
            if img.width > max_width:
                ratio = max_width / float(img.width)
                img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
            quality = current_app.config.get("IMAGE_QUALITY", 80)
            out_ext = {'JPEG': 'jpg', 'PNG': 'png', 'GIF': 'gif', 'WEBP': 'webp'}[fmt]
            path = os.path.join(upload_folder, f"{uuid.uuid4().hex}.{out_ext}")
            if fmt == 'JPEG':
                img.convert("RGB").save(path, format='JPEG', optimize=True, quality=quality)
            elif fmt == 'WEBP':
                img.save(path, format='WEBP', quality=quality)
            else:
                img.save(path, format=fmt, optimize=True)
    except Exception:
        return None
    return os.path.relpath(path, os.path.join(current_app.root_path, 'static')).replace("\\", "/")


def delete_uploaded_file(photo_url: Optional[str]) -> None:
    """Removes a previously uploaded photo. External http(s) URLs and paths outside uploads are ignored."""
    if not photo_url or photo_url.startswith(("http://", "https://")):
        return
    upload_folder = os.path.abspath(current_app.config["UPLOAD_FOLDER"])
    path = os.path.abspath(os.path.join(current_app.root_path, 'static', photo_url))
    if path.startswith(upload_folder + os.sep) and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


_email_env = SandboxedEnvironment(autoescape=False)


def render_email_template(template_string: str, context: dict) -> str:
    """Quick helper to render our editable email templates with Jinja placeholders."""
    return _email_env.from_string(template_string).render(**context)


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
    """Best effort loader that returns a ZoneInfo or timezone offset for labels."""
    try:
        return ZoneInfo(label)
    except ZoneInfoNotFoundError:
        offset = _timezone_offset_from_label(label)
        if offset:
            return timezone(offset)
    except Exception:
        return None
    return None


def _timezone_offset_from_label(label: str) -> timedelta:
    """Parses GMT/UTC style offsets like GMT+4 or UTC-05:30."""
    if not label:
        return timedelta()
    cleaned = label.strip().upper().replace('UTC', '').replace('GMT', '')
    match = re.match(r'^([+-])\s*(\d{1,2})(?::(\d{2}))?$', cleaned)
    if not match:
        return timedelta()
    sign = 1 if match.group(1) == '+' else -1
    hours = int(match.group(2))
    minutes = int(match.group(3)) if match.group(3) else 0
    return timedelta(hours=sign * hours, minutes=sign * minutes)


def format_display_time(dt, placeholder: str = "Not available", render_html: bool = True) -> str:
    """Human friendly label with configured timezone, or placeholder when dt missing."""
    tz_label = active_timezone_label()
    if not dt:
        return placeholder
    tzinfo = _zoneinfo_for(tz_label)
    base_dt = dt
    if dt.tzinfo is None:
        base_dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = base_dt.astimezone(timezone.utc)
    local_dt = utc_dt.astimezone(tzinfo) if tzinfo else utc_dt
    rendered = f"{local_dt.strftime('%d %b %Y, %H:%M')} ({tz_label})"
    return rendered


def local_to_utc_naive(local_dt):
    """Interprets an admin-entered naive datetime in the display timezone, returns naive UTC for storage."""
    if local_dt is None:
        return None
    tzinfo = _zoneinfo_for(active_timezone_label())
    if tzinfo is None:
        return local_dt
    return local_dt.replace(tzinfo=tzinfo).astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_local_input(dt) -> str:
    """Formats stored naive-UTC as the value of a <input type=datetime-local> in the display timezone."""
    if not dt:
        return ""
    tzinfo = _zoneinfo_for(active_timezone_label())
    aware = dt.replace(tzinfo=timezone.utc)
    local = aware.astimezone(tzinfo) if tzinfo else aware
    return local.strftime("%Y-%m-%dT%H:%M")


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def brand_style(election, default: str = "#7b7bff") -> str:
    """Inline CSS custom properties carrying an election's brand colours."""
    def pick(value, fallback):
        return value if value and _HEX.match(value) else fallback

    primary = pick(getattr(election, "theme_primary", None), default)
    secondary = pick(getattr(election, "theme_secondary", None), primary)
    accent = pick(getattr(election, "theme_accent", None), primary)
    on_primary = "#0b0c0e" if _luminance(primary) > 0.38 else "#ffffff"
    return f"--brand:{primary};--brand-2:{secondary};--brand-accent:{accent};--on-brand:{on_primary};"


def public_url(endpoint: str, **values) -> str:
    """Absolute URL for links that leave the app (emails, shareable results)."""
    base = current_app.config.get("PUBLIC_BASE_URL")
    if base:
        return base + url_for(endpoint, _external=False, **values)
    return url_for(endpoint, _external=True, **values)


def format_short_time(dt, placeholder: str = "—") -> str:
    """Compact timestamp for dense tables, in the display timezone."""
    if not dt:
        return placeholder
    tzinfo = _zoneinfo_for(active_timezone_label())
    utc_dt = dt.replace(tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(tzinfo) if tzinfo else utc_dt
    return local_dt.strftime("%d %b, %H:%M")
