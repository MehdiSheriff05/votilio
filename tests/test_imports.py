from app.imports import csv_safe, is_valid_email, normalize_header, validate_candidates, validate_voters
from tests.conftest import jpost, make_voter


def test_header_aliases():
    assert normalize_header("E-mail") == "email" and normalize_header(" Full Name ") == "name"
    assert normalize_header("Photo URL") == "photo_url" and normalize_header("Office") == "position"
    assert normalize_header("shoe size") is None


def test_email_validation():
    assert is_valid_email("a.b+c@example.co.uk")
    for bad in ["", "plain", "a@b", "a b@example.com", "a@@example.com", "a@example..com"]:
        assert not is_valid_email(bad), bad


def test_voter_rules():
    rows = [{"name": "A", "email": "a@example.com"}, {"name": "B", "email": "A@example.com"}, {"name": "C", "email": ""},
            {"name": "D", "email": "nope"}, {"name": "E", "email": "old@example.com"}, {"email": "ok@example.com"}]
    report = validate_voters(rows, existing_emails=["OLD@example.com"])
    assert [r.ok for r in report.rows] == [True, False, False, False, False, True]
    assert "Duplicate of row 1" in report.rows[1].errors["email"]
    assert "Already invited" in report.rows[4].errors["email"]


def test_candidate_rules_unknown_and_duplicates():
    positions = {"president": {"name": "President", "names": {"amina"}}}
    rows = [{"position": "president", "name": "Daniel"}, {"position": "President", "name": "Third"},
            {"position": "Treasurer", "name": "Priya"}, {"position": "President", "name": "amina"},
            {"position": "", "name": "X"}, {"position": "President", "name": ""},
            {"position": "President", "name": "Z", "photo_url": "javascript:alert(1)"}]
    r = validate_candidates(rows, positions)
    errs = [bool(x.errors) for x in r.rows]
    assert errs == [False, False, True, True, True, True, True]  # a third candidate is fine: no cap
    assert "Unknown position" in r.rows[2].errors["position"]
    assert "http" in r.rows[6].errors["photo_url"]


def test_candidate_create_missing_positions():
    rows = [{"position": "Secretary", "name": "A"}, {"position": "secretary", "name": "B"}, {"position": "Chair", "name": "C"}]
    r = validate_candidates(rows, {}, create_missing=True)
    assert all(x.ok for x in r.rows)
    assert sorted(p["name"] for p in r.new_positions) == ["Chair", "Secretary"]


def test_csv_formula_injection_neutralised():
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("+x") == "'+x" and csv_safe("plain") == "plain"


def test_voter_import_endpoints(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/voters")
    url = f"/admin/elections/{election.id}/voters/import"
    rows = [{"name": "A", "email": "a@example.com"}, {"name": "B", "email": "bad"}]
    r = jpost(admin_client, url + "/validate", {"rows": rows}, t)
    assert r.get_json()["invalid"] == 1
    blocked = jpost(admin_client, url, {"rows": rows}, t)
    assert blocked.status_code == 422
    ok = jpost(admin_client, url, {"rows": rows, "skip_invalid": True}, t)
    body = ok.get_json()
    assert body["created"] == 1 and body["skipped"] == 1 and body["rejected"][0]["errors"]["email"]
    again = jpost(admin_client, url, {"rows": [rows[0]]}, t)
    assert again.status_code == 422


def test_voter_import_generates_unique_keys(admin_client, election, token):
    from app.models import VoterInvitation
    t = token(f"/admin/elections/{election.id}/voters")
    rows = [{"name": f"V{i}", "email": f"v{i}@example.com"} for i in range(300)]
    r = jpost(admin_client, f"/admin/elections/{election.id}/voters/import", {"rows": rows}, t)
    assert r.get_json()["created"] == 300
    keys = [v.last_generated_key for v in VoterInvitation.query.all()]
    assert len(set(keys)) == 300 and all(len(k) == 6 and k.isdigit() for k in keys)


def test_import_rejects_garbage_and_oversize(admin_client, election, app, token):
    t = token(f"/admin/elections/{election.id}/voters")
    url = f"/admin/elections/{election.id}/voters/import"
    assert jpost(admin_client, url, {"nope": 1}, t).status_code == 400
    app.config["MAX_IMPORT_ROWS"] = 2
    assert jpost(admin_client, url, {"rows": [{}, {}, {}]}, t).status_code == 413


def test_import_requires_csrf_and_login(client, admin_client, election):
    no_csrf = admin_client.post(f"/admin/elections/{election.id}/voters/import", json={"rows": []})
    assert no_csrf.status_code == 400
    anon = client.__class__(client.application, client.response_wrapper).post(f"/admin/elections/{election.id}/voters/import", json={"rows": []})
    assert anon.status_code in (302, 400)


def test_candidate_import_creates_positions_and_respects_order(admin_client, election, token):
    from app.models import Candidate, Position
    t = token(f"/admin/elections/{election.id}/setup")
    rows = [{"position": "President", "name": "Third", "bio": "hi", "photo_url": "https://x.test/a.jpg"},
            {"position": "Treasurer", "name": "Priya"}, {"position": "Treasurer", "name": "Omar"}]
    r = jpost(admin_client, f"/admin/elections/{election.id}/candidates/import", {"rows": rows, "create_missing": True}, t)
    body = r.get_json()
    assert body["created"] == 3 and body["new_positions"] == 1
    treasurer = Position.query.filter_by(name="Treasurer").one()
    assert [c.name for c in treasurer.candidates] == ["Priya", "Omar"]
    third = Candidate.query.filter_by(name="Third").one()
    assert third.photo_url == "https://x.test/a.jpg" and third.order_index == 3
