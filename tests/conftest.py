import re

import pytest

from app import create_app, db
from app.models import AdminUser, Candidate, Election, Position, VoterInvitation
from config import TestConfig


@pytest.fixture
def app(tmp_path):
    import os
    import shutil
    import uuid

    static_uploads = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "static", "uploads", "_test_" + uuid.uuid4().hex[:8])

    class Cfg(TestConfig):
        UPLOAD_FOLDER = static_uploads

    app = create_app(Cfg)

    @app.before_request
    def _fresh_csrf_cache():
        # The fixture keeps one app context open, so Flask-WTF would otherwise reuse a token cached on g.
        from flask import g
        g.pop("csrf_token", None)

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
    shutil.rmtree(static_uploads, ignore_errors=True)


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(client, path="/admin/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


@pytest.fixture
def token(client):
    return lambda path="/admin/login": csrf_token(client, path)


@pytest.fixture
def admin_client(app, client):
    admin = AdminUser(username="admin", is_super_admin=True)
    admin.set_password("password123")
    db.session.add(admin)
    db.session.commit()
    resp = client.post("/admin/login", data={"username": "admin", "password": "password123", "csrf_token": csrf_token(client)})
    assert resp.status_code == 302
    return client


@pytest.fixture
def election(app):
    e = Election(name="Council", access_code="council", is_active=True)
    db.session.add(e)
    db.session.flush()
    pos = Position(election_id=e.id, name="President", candidate_slots=3, order_index=1)
    db.session.add(pos)
    db.session.flush()
    db.session.add_all([Candidate(position_id=pos.id, name="Amina", order_index=1), Candidate(position_id=pos.id, name="Daniel", order_index=2)])
    db.session.commit()
    return e


def make_voter(election, email="v@example.com", name="Vee", key="123456"):
    inv = VoterInvitation(election_id=election.id, name=name, email=email)
    inv.set_key(key)
    inv.last_generated_key = key
    db.session.add(inv)
    db.session.commit()
    return inv


def jpost(client, url, payload, token_value):
    return client.post(url, json=payload, headers={"X-CSRFToken": token_value, "X-Requested-With": "fetch"})
