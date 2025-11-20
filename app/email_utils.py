import random
import smtplib
from email.mime.text import MIMEText
from typing import Iterable

from flask import current_app

from app.models import SystemSettings

def generate_6_digit_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def send_email(recipients: Iterable[str], subject: str, body: str) -> None:
    settings = SystemSettings.get_or_create()
    host = settings.smtp_host or current_app.config.get("SMTP_HOST")
    port = settings.smtp_port or current_app.config.get("SMTP_PORT")
    username = settings.smtp_user or current_app.config.get("SMTP_USER")
    password = settings.smtp_password or current_app.config.get("SMTP_PASSWORD")
    sender = settings.mail_sender or current_app.config.get("MAIL_SENDER")

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(host, port) as server:
            if username and password:
                server.starttls()
                server.login(username, password)
            server.sendmail(sender, recipients, message.as_string())
    except Exception as exc:  # pragma: no cover - starter logging only
        current_app.logger.error("Failed to send email: %s", exc)
