from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Message:
    to: str
    subject: str
    text: str
    html: Optional[str] = None


@dataclass
class SendResult:
    ok: bool
    error: Optional[str] = None
    provider_id: Optional[str] = None


@dataclass
class MailConfig:
    provider: str = "smtp"
    sender: str = ""
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""


class Mailer:
    name = "base"

    def __init__(self, config: MailConfig):
        self.config = config

    def configuration_error(self) -> Optional[str]:
        raise NotImplementedError

    def send(self, message: Message) -> SendResult:
        return self.send_many([message])[0]

    def send_many(self, messages: List[Message]) -> List[SendResult]:
        raise NotImplementedError


def clean_header(value: str) -> str:
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split())
