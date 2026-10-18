import re
from html import escape

_URL = re.compile(r"(https?://[^\s<]+[^\s<.,;:!?)\]])")


def text_to_html(text: str) -> str:
    """Minimal, email-client-safe HTML version of a plain text message."""
    blocks = []
    for para in re.split(r"\n\s*\n", (text or "").strip()):
        safe = escape(para)
        safe = _URL.sub(r'<a href="\1" style="color:#4f46e5">\1</a>', safe).replace("\n", "<br>")
        blocks.append(f'<p style="margin:0 0 16px">{safe}</p>')
    body = "".join(blocks)
    return (
        '<!doctype html><html><body style="margin:0;padding:24px;background:#f6f7f9">'
        '<div style="max-width:520px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;'
        'border-radius:10px;padding:28px;font:15px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        f'color:#111827">{body}</div></body></html>'
    )
