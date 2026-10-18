from datetime import datetime, timedelta

from app import db
from app.models import Candidate, VoterInvitation, Vote
from tests.conftest import csrf_token, make_voter


def enter(client, code="council", key="123456"):
    return client.post("/", data={"election_code": code, "voting_key": key, "csrf_token": csrf_token(client, "/")})


def candidate_ids(election):
    return [c.id for c in Candidate.query.order_by(Candidate.id).all()]


def test_wrong_key_stays_on_page_with_error_and_keeps_code(client, election):
    make_voter(election)
    r = enter(client, key="000000")
    assert r.status_code == 200 and "invalid or has already been used" in r.get_data(as_text=True)
    assert 'value="council"' in r.get_data(as_text=True)


def test_unknown_election_code(client, election):
    r = enter(client, code="nope")
    assert r.status_code == 200 and "couldn&#39;t find that election code" in r.get_data(as_text=True)


def test_full_vote_flow_with_review_and_no_double_submit(client, election):
    make_voter(election)
    assert enter(client).status_code == 302
    ballot = client.get("/ballot")
    assert ballot.status_code == 200 and "President" in ballot.get_data(as_text=True)
    pos_id = election.positions[0].id
    cand = candidate_ids(election)[0]
    t = csrf_token(client, "/ballot")
    r = client.post("/ballot", data={f"position_{pos_id}": cand, "csrf_token": t})
    assert r.status_code == 302 and r.headers["Location"].endswith("/ballot/review")
    review = client.get("/ballot/review").get_data(as_text=True)
    assert "Amina" in review and "Submit ballot" in review
    assert Vote.query.count() == 0
    t = csrf_token(client, "/ballot/review")
    done = client.post("/ballot/submit", data={"csrf_token": t})
    assert done.status_code == 302 and done.headers["Location"].endswith("/thanks")
    assert Vote.query.count() == 1 and Vote.query.first().candidate_id == cand
    assert VoterInvitation.query.first().used is True
    assert "Your vote is in" in client.get("/thanks").get_data(as_text=True)
    assert client.get("/thanks").status_code == 200
    again = enter(client)
    assert again.status_code == 200 and "already been used" in again.get_data(as_text=True)


def test_vote_cannot_be_submitted_twice_from_stale_session(app, client, election):
    inv = make_voter(election)
    enter(client)
    pos_id = election.positions[0].id
    client.post("/ballot", data={f"position_{pos_id}": candidate_ids(election)[0], "csrf_token": csrf_token(client, "/ballot")})
    inv.used = True
    db.session.commit()
    r = client.post("/ballot/submit", data={"csrf_token": csrf_token(client, "/")})
    assert r.status_code == 302 and Vote.query.count() == 0


def test_skipping_a_position_is_allowed_and_shown(client, election):
    make_voter(election)
    enter(client)
    client.post("/ballot", data={"csrf_token": csrf_token(client, "/ballot")})
    assert "No selection" in client.get("/ballot/review").get_data(as_text=True)
    client.post("/ballot/submit", data={"csrf_token": csrf_token(client, "/ballot/review")})
    assert Vote.query.count() == 0 and VoterInvitation.query.first().used


def test_candidate_from_another_position_is_ignored(client, election):
    make_voter(election)
    enter(client)
    client.post("/ballot", data={f"position_{election.positions[0].id}": 9999, "csrf_token": csrf_token(client, "/ballot")})
    assert "No selection" in client.get("/ballot/review").get_data(as_text=True)


def test_closed_and_scheduled_elections_block_entry(client, election):
    make_voter(election)
    election.end_time = datetime.utcnow() - timedelta(hours=1)
    db.session.commit()
    assert "closed" in enter(client).get_data(as_text=True)
    election.end_time, election.start_time = None, datetime.utcnow() + timedelta(hours=1)
    db.session.commit()
    assert "not started" in enter(client).get_data(as_text=True)


def test_paused_election_hides_itself(client, election):
    make_voter(election)
    election.is_active = False
    db.session.commit()
    assert "couldn&#39;t find" in enter(client).get_data(as_text=True)


def test_ballot_requires_session(client, election):
    assert client.get("/ballot").status_code == 302
    assert client.get("/ballot/review").status_code == 302


def test_deep_link_prefills_and_brands(client, election):
    election.theme_primary = "#ff5500"
    db.session.commit()
    html = client.get("/?code=council").get_data(as_text=True)
    assert 'value="council"' in html and "--brand:#ff5500" in html


def test_key_with_spaces_and_dashes_is_accepted(client, election):
    make_voter(election, key="123456")
    assert enter(client, key="123 456").status_code == 302


def test_admin_session_survives_voter_activity(admin_client, election):
    make_voter(election)
    enter(admin_client)
    assert admin_client.get("/admin/").status_code == 200


def test_public_results_only_when_published(admin_client, client, election, token):
    assert client.get("/results/anything").status_code == 404
    t = token(f"/admin/elections/{election.id}/results")
    admin_client.post(f"/admin/elections/{election.id}/results/publish", data={"state": "publish", "csrf_token": t})
    db.session.refresh(election)
    assert election.results_public
    anon = client.application.test_client()
    page = anon.get(f"/results/{election.results_slug}")
    assert page.status_code == 200 and "President" in page.get_data(as_text=True)


def test_legacy_scrypt_keys_still_work(client, election):
    from werkzeug.security import generate_password_hash
    inv = VoterInvitation(election_id=election.id, email="old@example.com", voting_key_hash=generate_password_hash("654321"))
    db.session.add(inv)
    db.session.commit()
    assert enter(client, key="654321").status_code == 302


def test_keys_survive_secret_key_rotation(app, client, election):
    make_voter(election, key="777777")
    app.config["SECRET_KEY"] = "a-completely-different-secret-key-0123456789"
    assert enter(client, key="777777").status_code == 302
    assert VoterInvitation.query.first().check_key("777777")
