import pytest

from app import create_app, db, limiter
from config import TestConfig
from tests.conftest import csrf_token, make_voter
from app.models import Election


@pytest.fixture
def limited_client(tmp_path):
    class Cfg(TestConfig):
        RATELIMIT_ENABLED = True
        UPLOAD_FOLDER = str(tmp_path / "u")

    app = create_app(Cfg)

    @app.before_request
    def _fresh():
        from flask import g
        g.pop("csrf_token", None)

    with app.app_context():
        db.create_all()
        limiter.reset()
        yield app
        limiter.reset()
        db.session.remove()
        db.drop_all()


def test_failed_voter_keys_are_throttled_but_successes_are_not(limited_client):
    app = limited_client
    e = Election(name="E", access_code="e", is_active=True)
    db.session.add(e)
    db.session.commit()
    for i in range(12):
        make_voter(e, f"v{i}@example.com", key=f"10000{i}" if i < 10 else f"1000{i}")
    for i in range(12):
        c = app.test_client()
        key = f"10000{i}" if i < 10 else f"1000{i}"
        r = c.post("/", data={"election_code": "e", "voting_key": key, "csrf_token": csrf_token(c, "/")})
        assert r.status_code == 302, (i, r.status_code)
    c = app.test_client()
    codes = []
    for _ in range(12):
        codes.append(c.post("/", data={"election_code": "e", "voting_key": "999999", "csrf_token": csrf_token(c, "/")}).status_code)
    assert codes[:10] == [200] * 10 and 429 in codes[10:]


def test_admin_login_is_throttled(limited_client):
    c = limited_client.test_client()
    codes = [c.post("/admin/login", data={"username": "x", "password": "y", "csrf_token": csrf_token(c)}).status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[-1] == 429
