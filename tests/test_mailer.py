from unittest.mock import MagicMock, patch

import pytest
from aiosmtpd.controller import Controller

from app import db
from app.mailer import Message, build_mailer, load_config, send_messages
from app.mailer.base import MailConfig
from app.mailer.resend import ResendMailer
from app.mailer.smtp import SMTPMailer
from app.models import SystemSettings


class Collector:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 OK"


@pytest.fixture
def smtp_server():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    handler = Collector()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    yield handler, port
    controller.stop()


def resp(status=200, body=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {"id": "abc"}
    r.text = str(body)
    r.headers = headers or {}
    return r


def test_smtp_sends_text_and_html(smtp_server):
    handler, port = smtp_server
    cfg = MailConfig(provider="smtp", sender="Votilio <vote@example.com>", smtp_host="127.0.0.1", smtp_port=port, smtp_security="none")
    result = SMTPMailer(cfg).send(Message("a@example.com", "Hello", "plain body", "<p>html body</p>"))
    assert result.ok, result.error
    raw = handler.messages[0].content.decode()
    assert "plain body" in raw and "html body" in raw and "Subject: Hello" in raw
    assert handler.messages[0].rcpt_tos == ["a@example.com"]


def test_smtp_many_reuses_connection_and_reports_failure_per_message():
    cfg = MailConfig(provider="smtp", sender="x@example.com", smtp_host="127.0.0.1", smtp_port=1, smtp_security="none")
    results = SMTPMailer(cfg).send_many([Message("a@example.com", "s", "b"), Message("b@example.com", "s", "b")])
    assert [r.ok for r in results] == [False, False]
    assert "Could not connect" in results[0].error


def test_smtp_missing_host_is_a_clear_error():
    r = SMTPMailer(MailConfig(sender="x@example.com")).send(Message("a@example.com", "s", "b"))
    assert not r.ok and "host" in r.error.lower()


def test_header_injection_is_neutralised(smtp_server):
    handler, port = smtp_server
    cfg = MailConfig(provider="smtp", sender="x@example.com", smtp_host="127.0.0.1", smtp_port=port, smtp_security="none")
    SMTPMailer(cfg).send(Message("a@example.com", "Hi\r\nBcc: evil@example.com", "b"))
    raw = handler.messages[0].content.decode()
    assert "\nBcc:" not in raw


CFG = MailConfig(provider="resend", sender="Votilio <vote@example.com>", resend_api_key="re_test")


def test_resend_single_request_shape():
    with patch("app.mailer.resend.requests.post", return_value=resp(200, {"id": "m1"})) as post:
        r = ResendMailer(CFG).send(Message("a@example.com", "Subj", "text", "<p>html</p>"))
    assert r.ok and r.provider_id == "m1"
    args, kwargs = post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_test"
    assert kwargs["json"] == {"from": "Votilio <vote@example.com>", "to": ["a@example.com"], "subject": "Subj", "text": "text", "html": "<p>html</p>"}


def test_resend_uses_batch_endpoint_and_maps_ids():
    msgs = [Message(f"u{i}@example.com", "s", "b") for i in range(3)]
    with patch("app.mailer.resend.requests.post", return_value=resp(200, {"data": [{"id": "1"}, {"id": "2"}, {"id": "3"}]})) as post:
        results = ResendMailer(CFG).send_many(msgs)
    assert post.call_args[0][0].endswith("/emails/batch") and len(post.call_args[1]["json"]) == 3
    assert [r.provider_id for r in results] == ["1", "2", "3"]


def test_resend_batch_validation_error_falls_back_to_individual_sends():
    def fake(url, **kw):
        if url.endswith("/batch"):
            return resp(422, {"message": "bad address"})
        return resp(422, {"message": "Invalid `to` field"}) if kw["json"]["to"] == ["bad"] else resp(200, {"id": "ok"})
    msgs = [Message("good@example.com", "s", "b"), Message("bad", "s", "b")]
    with patch("app.mailer.resend.requests.post", side_effect=fake):
        results = ResendMailer(CFG).send_many(msgs)
    assert results[0].ok and not results[1].ok and "Invalid" in results[1].error


def test_resend_retries_rate_limit_then_succeeds():
    seq = [resp(429, {"message": "slow"}, {"retry-after": "0"}), resp(200, {"id": "z"})]
    with patch("app.mailer.resend.requests.post", side_effect=seq), patch("app.mailer.resend.time.sleep"):
        assert ResendMailer(CFG).send(Message("a@example.com", "s", "b")).ok


def test_resend_auth_error_surfaces_message():
    with patch("app.mailer.resend.requests.post", return_value=resp(401, {"message": "API key is invalid"})):
        r = ResendMailer(CFG).send(Message("a@example.com", "s", "b"))
    assert not r.ok and "API key is invalid" in r.error


def test_resend_without_key_does_not_call_network():
    with patch("app.mailer.resend.requests.post") as post:
        r = ResendMailer(MailConfig(provider="resend", sender="x@example.com")).send(Message("a@example.com", "s", "b"))
    assert not r.ok and not post.called


def test_provider_selection_env_beats_db(app):
    settings = SystemSettings.get_or_create()
    settings.email_provider = "smtp"
    db.session.commit()
    assert load_config().provider == "smtp"
    app.config["EMAIL_PROVIDER"] = "resend"
    assert load_config().provider == "resend"
    assert isinstance(build_mailer(), ResendMailer)
    assert load_config(overrides={"provider": "smtp"}).provider == "smtp"


def test_secrets_are_encrypted_at_rest(app):
    settings = SystemSettings.get_or_create()
    settings.resend_api_key_plain = "re_supersecret"
    settings.smtp_password_plain = "hunter2"
    db.session.commit()
    assert "re_supersecret" not in settings.resend_api_key and settings.resend_api_key.startswith("enc:v1:")
    assert settings.smtp_password.startswith("enc:v1:")
    assert settings.resend_api_key_plain == "re_supersecret" and settings.smtp_password_plain == "hunter2"
    assert load_config(settings).resend_api_key == "re_supersecret"


def test_send_messages_never_raises(app):
    with patch("app.mailer.build_mailer", side_effect=RuntimeError("boom")):
        results = send_messages([Message("a@example.com", "s", "b")])
    assert not results[0].ok and "boom" in results[0].error
