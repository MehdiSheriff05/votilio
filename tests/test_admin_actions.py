import io
from unittest.mock import patch

from PIL import Image

from app import db
from app.mailer import SendResult
from app.models import Candidate, Election, Position, SystemSettings, Vote, VoterInvitation
from tests.conftest import jpost, make_voter


def form(client, url, data, token_value, **kw):
    data = dict(data, csrf_token=token_value)
    return client.post(url, data=data, headers={"X-Requested-With": "fetch", "Accept": "application/json"}, **kw)


def png_bytes(size=(1200, 800)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_create_election_autogenerates_code_and_converts_timezone(admin_client, app, token):
    t = token("/admin/elections/create")
    SystemSettings.get_or_create().timezone_name = "GMT+4"
    db.session.commit()
    r = admin_client.post("/admin/elections/create", data={"name": "Fresh Vote", "start_time": "2026-05-01T09:00", "end_time": "2026-05-02T17:00", "csrf_token": t})
    assert r.status_code == 302
    e = Election.query.filter_by(name="Fresh Vote").one()
    assert e.access_code.startswith("fresh-vote-")
    assert e.start_time.hour == 5
    page = admin_client.get(f"/admin/elections/{e.id}/setup").get_data(as_text=True)
    assert 'value="2026-05-01T09:00"' in page


def test_duplicate_election_code_rejected(admin_client, election, token):
    t = token("/admin/elections/create")
    r = admin_client.post("/admin/elections/create", data={"name": "Other", "access_code": "COUNCIL", "csrf_token": t})
    assert r.status_code == 200 and Election.query.count() == 1


def test_position_and_candidate_crud_with_photo(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/setup")
    r = form(admin_client, f"/admin/elections/{election.id}/positions/create", {"name": "Treasurer"}, t)
    assert r.get_json()["ok"]
    pos = Position.query.filter_by(name="Treasurer").one()
    up = form(admin_client, f"/admin/positions/{pos.id}/candidates/create", {"name": "Priya", "description": "bio", "photo": (png_bytes(), "p.png")}, t, content_type="multipart/form-data")
    assert up.get_json()["ok"]
    cand = Candidate.query.filter_by(name="Priya").one()
    assert cand.photo_url.startswith("uploads/") and cand.photo_url.endswith(".png")
    with Image.open(f"{admin_client.application.config['UPLOAD_FOLDER']}/{cand.photo_url.split('/')[-1]}") as img:
        assert img.width == 800
    bad = form(admin_client, f"/admin/positions/{pos.id}/candidates/create", {"name": "Fake", "photo": (io.BytesIO(b"not an image"), "x.png")}, t, content_type="multipart/form-data")
    assert bad.status_code == 400 and Candidate.query.filter_by(name="Fake").count() == 0
    assert form(admin_client, f"/admin/positions/{pos.id}/candidates/create", {"name": "Omar"}, t).get_json()["ok"]
    third = form(admin_client, f"/admin/positions/{pos.id}/candidates/create", {"name": "Third"}, t)
    assert third.get_json()["ok"] and len(pos.candidates) == 3  # no cap on how many can stand
    old = cand.photo_url
    form(admin_client, f"/admin/candidates/{cand.id}/update", {"name": "Priya N", "remove_photo": "on"}, t)
    db.session.refresh(cand)
    assert cand.photo_url is None and cand.name == "Priya N"
    import os
    assert not os.path.exists(os.path.join(admin_client.application.root_path, "static", old))


def test_cannot_delete_candidate_or_position_with_votes(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/setup")
    pos = election.positions[0]
    cand = pos.candidates[0]
    db.session.add(Vote(election_id=election.id, position_id=pos.id, candidate_id=cand.id))
    db.session.commit()
    assert form(admin_client, f"/admin/candidates/{cand.id}/delete", {}, t).status_code == 409
    assert form(admin_client, f"/admin/positions/{pos.id}/delete", {}, t).status_code == 409
    other = pos.candidates[1]
    assert form(admin_client, f"/admin/candidates/{other.id}/delete", {}, t).get_json()["ok"]


def test_reorder_positions_and_candidates(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/setup")
    p2 = Position(election_id=election.id, name="Treasurer", order_index=2)
    db.session.add(p2)
    db.session.commit()
    first = election.positions[0]
    assert jpost(admin_client, f"/admin/elections/{election.id}/positions/reorder", {"ids": [p2.id, first.id]}, t).status_code == 200
    db.session.expire_all()
    assert [p.name for p in Position.query.order_by(Position.order_index)] == ["Treasurer", "President"]
    ids = [c.id for c in first.candidates]
    jpost(admin_client, f"/admin/positions/{first.id}/candidates/reorder", {"ids": list(reversed(ids))}, t)
    db.session.expire_all()
    assert [c.id for c in Position.query.get(first.id).candidates] == list(reversed(ids))


def test_voter_crud_and_duplicates(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/voters")
    ok = form(admin_client, f"/admin/elections/{election.id}/voters/add", {"name": "Zed", "email": "zed@example.com"}, t)
    assert ok.get_json()["ok"]
    assert form(admin_client, f"/admin/elections/{election.id}/voters/add", {"email": "ZED@example.com"}, t).status_code == 409
    assert form(admin_client, f"/admin/elections/{election.id}/voters/add", {"email": "bad"}, t).status_code == 400
    inv = VoterInvitation.query.one()
    assert len(inv.last_generated_key) == 6 and inv.check_key(inv.last_generated_key)
    assert form(admin_client, f"/admin/invitations/{inv.id}/update", {"name": "Zed Z", "email": "zz@example.com"}, t).get_json()["ok"]
    inv.used = True
    db.session.commit()
    assert form(admin_client, f"/admin/invitations/{inv.id}/delete", {}, t).status_code == 409


def test_bulk_delete_skips_voted(admin_client, election, token):
    a, b = make_voter(election, "a@example.com", key="111111"), make_voter(election, "b@example.com", key="222222")
    b.used = True
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/voters")
    r = admin_client.post(f"/admin/elections/{election.id}/voters/bulk-delete", data={"ids": [a.id, b.id], "csrf_token": t}, headers={"X-Requested-With": "fetch"})
    assert r.get_json()["ok"] and VoterInvitation.query.count() == 1


def _ok_mailer(results_ok=True):
    def fake(messages, config=None):
        return [SendResult(results_ok, None if results_ok else "mailbox full") for _ in messages]
    return patch("app.admin.voters.send_messages", side_effect=fake)


def test_chunked_send_marks_only_successes_and_paginates(admin_client, election, token, app):
    app.config["EMAIL_CHUNK_SIZE"] = 2
    for i in range(5):
        make_voter(election, f"v{i}@example.com", key=f"10000{i}")
    t = token(f"/admin/elections/{election.id}/voters")
    url = f"/admin/elections/{election.id}/send"
    with _ok_mailer():
        cursor, sent, rounds = 0, 0, 0
        while True:
            d = jpost(admin_client, url, {"kind": "invite", "cursor": cursor}, t).get_json()
            sent, cursor, rounds = sent + d["sent"], d["cursor"], rounds + 1
            if d["done"]:
                break
    assert sent == 5 and rounds == 3
    assert VoterInvitation.query.filter(VoterInvitation.sent_at.isnot(None)).count() == 5
    with _ok_mailer():
        assert jpost(admin_client, url, {"kind": "invite", "cursor": 0}, t).get_json()["sent"] == 0


def test_failed_sends_are_reported_and_not_marked_sent(admin_client, election, token):
    make_voter(election, "x@example.com")
    t = token(f"/admin/elections/{election.id}/voters")
    with _ok_mailer(False):
        d = jpost(admin_client, f"/admin/elections/{election.id}/send", {"kind": "invite", "cursor": 0}, t).get_json()
    assert d["sent"] == 0 and d["failed"][0]["error"] == "mailbox full"
    assert VoterInvitation.query.one().sent_at is None


def test_reminders_target_only_invited_and_not_voted(admin_client, election, token):
    a, b, c = (make_voter(election, f"{n}@example.com", key=k) for n, k in (("a", "111111"), ("b", "222222"), ("c", "333333")))
    from datetime import datetime
    a.sent_at = b.sent_at = datetime.utcnow()
    b.used = True
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/voters")
    with _ok_mailer():
        d = jpost(admin_client, f"/admin/elections/{election.id}/send", {"kind": "reminder", "cursor": 0}, t).get_json()
    assert d["sent"] == 1
    db.session.refresh(a)
    assert a.reminder_sent_at is not None


def test_email_contains_key_code_and_prefilled_link(admin_client, election, token):
    make_voter(election, "k@example.com", key="424242")
    t = token(f"/admin/elections/{election.id}/voters")
    captured = {}

    def fake(messages, config=None):
        captured["m"] = messages[0]
        return [SendResult(True)]
    with patch("app.admin.voters.send_messages", side_effect=fake):
        jpost(admin_client, f"/admin/elections/{election.id}/send", {"kind": "invite", "cursor": 0}, t)
    m = captured["m"]
    assert "424242" in m.text and "council" in m.text and "?code=council" in m.text and "<a href" in m.html


def test_settings_save_is_write_only_for_secrets(admin_client, token):
    t = token("/admin/settings/email")
    data = {"email_provider": "resend", "resend_api_key": "re_live_abc123", "smtp_host": "", "smtp_port": "587", "smtp_security": "starttls",
            "mail_sender": "V <v@example.com>", "invite_subject": "Hi {{ election_name }}", "invite_body": "Key {{ voting_key }}",
            "reminder_subject": "R", "reminder_body": "R {{ voting_key }}"}
    assert form(admin_client, "/admin/settings/email", data, t).get_json()["ok"]
    s = SystemSettings.query.first()
    assert s.email_provider == "resend" and s.resend_api_key_plain == "re_live_abc123"
    page = admin_client.get("/admin/settings/email").get_data(as_text=True)
    assert "re_live_abc123" not in page and "saved. Type to replace" in page
    data["resend_api_key"] = ""
    form(admin_client, "/admin/settings/email", data, t)
    assert SystemSettings.query.first().resend_api_key_plain == "re_live_abc123"


def test_settings_rejects_broken_templates_and_unsafe_access(admin_client, token):
    t = token("/admin/settings/email")
    base = {"email_provider": "smtp", "smtp_port": "25", "smtp_security": "none", "mail_sender": "a@b.co", "invite_subject": "{{ unclosed",
            "invite_body": "x", "reminder_subject": "x", "reminder_body": "x"}
    assert form(admin_client, "/admin/settings/email", base, t).status_code == 400
    base["invite_subject"] = "{{ ''.__class__.__mro__ }}"
    assert form(admin_client, "/admin/settings/email", base, t).status_code == 400


def test_test_email_endpoint_uses_unsaved_values(admin_client, token):
    t = token("/admin/settings/email")
    with patch("app.mailer.resend.requests.post") as post:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"id": "t1"}
        r = jpost(admin_client, "/admin/settings/email/test", {"to": "me@example.com", "provider": "resend", "resend_api_key": "re_x", "mail_sender": "V <v@example.com>"}, t)
    assert r.get_json()["ok"] and post.call_args[1]["json"]["to"] == ["me@example.com"]
    assert jpost(admin_client, "/admin/settings/email/test", {"to": "nope"}, t).status_code == 400


def test_regular_admin_cannot_reach_settings_or_delete_election(app, client, election, token):
    from app.models import AdminUser
    u = AdminUser(username="reg", is_super_admin=False)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    client.post("/admin/login", data={"username": "reg", "password": "password123", "csrf_token": token()})
    assert client.get("/admin/settings/email").status_code == 302
    r = client.post(f"/admin/elections/{election.id}/delete", data={"csrf_token": token("/admin/")})
    assert r.status_code == 302 and Election.query.count() == 1


def test_delete_election_with_votes(admin_client, election, token):
    pos = election.positions[0]
    db.session.add(Vote(election_id=election.id, position_id=pos.id, candidate_id=pos.candidates[0].id))
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/setup")
    assert form(admin_client, f"/admin/elections/{election.id}/delete", {}, t).get_json()["ok"]
    assert Election.query.count() == 0 and Vote.query.count() == 0


def test_toggle_pause_and_results_export_escapes_formulas(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/setup")
    form(admin_client, f"/admin/elections/{election.id}/toggle", {}, t)
    db.session.refresh(election)
    assert election.is_active is False and election.status() == "paused"
    election.positions[0].candidates[0].name = "=cmd|calc"
    db.session.commit()
    csv_text = admin_client.get(f"/admin/elections/{election.id}/results.csv").get_data(as_text=True)
    assert "'=cmd|calc" in csv_text


def test_logout_is_post_only_and_clears_session(admin_client, token):
    assert admin_client.get("/admin/logout").status_code == 405
    admin_client.post("/admin/logout", data={"csrf_token": token("/admin/")})
    assert admin_client.get("/admin/").status_code == 302


def test_special_characters_in_election_code_survive_the_email_link(admin_client, election, token, client):
    election.access_code = "Café 2026&x=1"
    db.session.commit()
    make_voter(election, "s@example.com", key="515151")
    t = token(f"/admin/elections/{election.id}/voters")
    captured = {}

    def fake(messages, config=None):
        captured["m"] = messages[0]
        return [SendResult(True)]
    with patch("app.admin.voters.send_messages", side_effect=fake):
        jpost(admin_client, f"/admin/elections/{election.id}/send", {"kind": "invite", "cursor": 0}, t)
    link = [w for w in captured["m"].text.split() if "?code=" in w][0]
    assert link.endswith("?code=Caf%C3%A9%202026%26x%3D1")
    page = client.application.test_client().get("/" + link.split("/", 3)[-1]).get_data(as_text=True)
    assert 'value="Café 2026&amp;x=1"' in page


def test_bulk_key_export_is_super_admin_only(app, client, election, token):
    from app.models import AdminUser
    u = AdminUser(username="reg", is_super_admin=False)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    client.post("/admin/login", data={"username": "reg", "password": "password123", "csrf_token": token()})
    assert client.get(f"/admin/elections/{election.id}/voter-keys.csv").status_code == 302
    assert client.get(f"/admin/elections/{election.id}/voters").status_code == 200
