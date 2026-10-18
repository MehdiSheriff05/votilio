"""Encrypt small secrets (API keys, SMTP passwords) at rest, keyed from FLASK_SECRET_KEY."""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    secret = current_app.config["SECRET_KEY"].encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(b"votilio-secrets-box:" + secret).digest())
    return Fernet(key)


def encrypt(plain: Optional[str]) -> Optional[str]:
    if not plain:
        return None
    return PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt(stored: Optional[str]) -> str:
    """Returns the plaintext. Legacy un-prefixed values are returned unchanged."""
    if not stored:
        return ""
    if not stored.startswith(PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        current_app.logger.error("Could not decrypt a stored secret; was FLASK_SECRET_KEY changed?")
        return ""
