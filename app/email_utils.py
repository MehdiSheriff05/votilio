import secrets

from app.mailer import send_email  # noqa: F401  (re-exported for existing callers)


def generate_6_digit_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
