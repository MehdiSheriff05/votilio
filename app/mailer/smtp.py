import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from typing import List, Optional

from app.mailer.base import MailConfig, Mailer, Message, SendResult, clean_header

TIMEOUT = 20


class SMTPMailer(Mailer):
    name = "smtp"

    def configuration_error(self) -> Optional[str]:
        c = self.config
        if not c.smtp_host:
            return "SMTP host is not set."
        if not c.sender:
            return "Sender address is not set."
        if c.smtp_security not in {"none", "starttls", "ssl"}:
            return "SMTP security must be none, starttls or ssl."
        if bool(c.smtp_user) != bool(c.smtp_password):
            return "Set both the SMTP username and password, or neither."
        return None

    def _build(self, message: Message) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = clean_header(message.subject)
        msg["From"] = clean_header(self.config.sender)
        msg["To"] = clean_header(message.to)
        msg["Date"] = formatdate(localtime=False)
        domain = parseaddr(self.config.sender)[1].rpartition("@")[2] or None
        msg["Message-ID"] = make_msgid(domain=domain)
        msg.set_content(message.text)
        if message.html:
            msg.add_alternative(message.html, subtype="html")
        return msg

    def _connect(self) -> smtplib.SMTP:
        c = self.config
        context = ssl.create_default_context()
        if c.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(c.smtp_host, c.smtp_port, timeout=TIMEOUT, context=context)
        else:
            server = smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=TIMEOUT)
            server.ehlo()
            if c.smtp_security == "starttls":
                server.starttls(context=context)
                server.ehlo()
        if c.smtp_user:
            server.login(c.smtp_user, c.smtp_password)
        return server

    def send_many(self, messages: List[Message]) -> List[SendResult]:
        error = self.configuration_error()
        if error:
            return [SendResult(False, error) for _ in messages]
        try:
            server = self._connect()
        except Exception as exc:
            reason = f"Could not connect to {self.config.smtp_host}:{self.config.smtp_port}: {exc}"
            return [SendResult(False, reason) for _ in messages]
        results: List[SendResult] = []
        try:
            for message in messages:
                try:
                    built = self._build(message)
                    server.send_message(built)
                    results.append(SendResult(True, provider_id=built["Message-ID"]))
                except smtplib.SMTPServerDisconnected:
                    try:
                        server = self._connect()
                        server.send_message(self._build(message))
                        results.append(SendResult(True))
                    except Exception as exc:
                        results.append(SendResult(False, str(exc)))
                except Exception as exc:
                    results.append(SendResult(False, str(exc)))
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return results
