import random
import smtplib
import threading
from email.mime.text import MIMEText
from typing import Iterable

from flask import current_app

from app.models import SystemSettings

def generate_6_digit_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _send_email_sync(recipients: Iterable[str], subject: str, body: str) -> None:
    settings = SystemSettings.get_or_create()
    host = settings.smtp_host or current_app.config.get("SMTP_HOST")
    port = settings.smtp_port or current_app.config.get("SMTP_PORT")
    username = settings.smtp_user or current_app.config.get("SMTP_USER")
    password = settings.smtp_password or current_app.config.get("SMTP_PASSWORD")
    sender = settings.mail_sender or current_app.config.get("MAIL_SENDER")
    use_tls = current_app.config.get("SMTP_USE_TLS", True)

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
                server.ehlo()
            if username and password:
                server.login(username, password)
            server.sendmail(sender, recipients, message.as_string())
    except Exception as exc:  # pragma: no cover - starter logging only
        current_app.logger.error("Failed to send email: %s", exc)


def send_email(recipients: Iterable[str], subject: str, body: str) -> None:
    """Dispatch email, optionally using a background thread."""
    if current_app.config.get("SEND_EMAIL_ASYNC", True):
        app = current_app._get_current_object()

        def _run_with_context() -> None:
            with app.app_context():
                _send_email_sync(list(recipients), subject, body)

        threading.Thread(target=_run_with_context, daemon=True).start()
        return
    _send_email_sync(recipients, subject, body)
