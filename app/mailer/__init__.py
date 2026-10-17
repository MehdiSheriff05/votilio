from typing import Iterable, List, Optional

from flask import current_app

from app.mailer.base import MailConfig, Mailer, Message, SendResult
from app.mailer.render import text_to_html
from app.mailer.resend import ResendMailer
from app.mailer.smtp import SMTPMailer

PROVIDERS = {"smtp": SMTPMailer, "resend": ResendMailer}

__all__ = ["MailConfig", "Message", "SendResult", "build_mailer", "load_config", "send_email",
           "send_messages", "text_to_html", "active_provider", "PROVIDERS"]


def load_config(settings=None, overrides: Optional[dict] = None) -> MailConfig:
    """Resolve effective mail settings: environment first for provider/key, else the admin-saved row."""
    from app.models import SystemSettings

    cfg = current_app.config
    settings = settings or SystemSettings.get_or_create()
    overrides = overrides or {}

    provider = overrides.get("provider") or cfg.get("EMAIL_PROVIDER") or settings.email_provider or "smtp"
    key = overrides.get("resend_api_key") or cfg.get("RESEND_API_KEY") or settings.resend_api_key_plain
    password = overrides.get("smtp_password") or settings.smtp_password_plain or cfg.get("SMTP_PASSWORD") or ""
    return MailConfig(
        provider=provider if provider in PROVIDERS else "smtp",
        sender=(overrides.get("mail_sender") or settings.mail_sender or cfg.get("MAIL_SENDER") or "").strip(),
        resend_api_key=key or "",
        smtp_host=(overrides.get("smtp_host") or settings.smtp_host or cfg.get("SMTP_HOST") or "").strip(),
        smtp_port=int(overrides.get("smtp_port") or settings.smtp_port or cfg.get("SMTP_PORT") or 587),
        smtp_security=(overrides.get("smtp_security") or settings.smtp_security or cfg.get("SMTP_SECURITY") or "starttls"),
        smtp_user=(overrides.get("smtp_user") if "smtp_user" in overrides else (settings.smtp_user or cfg.get("SMTP_USER") or "")).strip(),
        smtp_password=password,
    )


def build_mailer(config: Optional[MailConfig] = None) -> Mailer:
    config = config or load_config()
    return PROVIDERS[config.provider](config)


def active_provider() -> str:
    return load_config().provider


def send_messages(messages: List[Message], config: Optional[MailConfig] = None) -> List[SendResult]:
    if not messages:
        return []
    try:
        return build_mailer(config).send_many(messages)
    except Exception as exc:  # last-resort guard so a provider bug never 500s a bulk send
        current_app.logger.exception("Mailer crashed")
        return [SendResult(False, f"Unexpected mail error: {exc}") for _ in messages]


def send_email(recipients: Iterable[str], subject: str, body: str) -> SendResult:
    """Send one message (plain text plus generated HTML) to the first recipient."""
    recipients = list(recipients)
    if not recipients:
        return SendResult(False, "No recipient.")
    results = send_messages([Message(recipients[0], subject, body, text_to_html(body))])
    result = results[0]
    if not result.ok:
        current_app.logger.error("Email to %s failed: %s", recipients[0], result.error)
    return result
