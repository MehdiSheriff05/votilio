from datetime import datetime
from unittest.mock import patch

from app import db
from app.mailer import SendResult
from app.models import Candidate, Election, Position, Vote, VoterInvitation
from tests.conftest import csrf_token, jpost, make_voter


def add_votes(election, position, candidate, n):
    for _ in range(n):
        db.session.add(Vote(election_id=election.id, position_id=position.id, candidate_id=candidate.id))
    db.session.commit()


def block(election, name="President"):
    return next(b for b in election.summarize_results() if b["position"].name == name)


def names(candidates):
    return [c.name for c in candidates]


def setup_votes(election, amina=5, daniel=3):
    pos = election.positions[0]
    a, d = pos.candidates
    add_votes(election, pos, a, amina)
    add_votes(election, pos, d, daniel)
    return pos, a, d


def test_highest_count_wins(election):
    setup_votes(election)
    b = block(election)
    assert names(b["winners"]) == ["Amina"] and b["tied"] == []
    assert [i["status"] for i in b["candidates"]] == ["winner", None]


def test_resigned_candidate_gives_the_seat_to_the_runner_up(election):
    pos, a, d = setup_votes(election)
    a.is_declined = True
    db.session.commit()
    b = block(election)
    assert names(b["winners"]) == ["Daniel"]
    assert [i["status"] for i in b["candidates"]] == ["resigned", "winner"]


def test_dismissed_is_skipped_and_everyone_out_means_no_winner(election):
    pos, a, d = setup_votes(election)
    a.is_disqualified = True
    d.is_declined = True
    db.session.commit()
    b = block(election)
    assert b["winners"] == [] and {i["status"] for i in b["candidates"]} == {"dismissed", "resigned"}


def test_tie_for_the_only_seat_is_reported_not_guessed(election):
    setup_votes(election, 4, 4)
    b = block(election)
    assert b["winners"] == [] and names(b["tied"]) == ["Amina", "Daniel"]


def test_manual_override_decides_a_tie_and_beats_the_count(election):
    pos, a, d = setup_votes(election, 4, 4)
    pos.winner_override_id = d.id
    db.session.commit()
    b = block(election)
    assert names(b["winners"]) == ["Daniel"] and b["tied"] == [] and b["override"].id == d.id
    add_votes(election, pos, a, 10)
    assert names(block(election)["winners"]) == ["Daniel"]


def test_override_is_ignored_if_that_candidate_resigns(election):
    pos, a, d = setup_votes(election)
    pos.winner_override_id = d.id
    d.is_declined = True
    db.session.commit()
    assert names(block(election)["winners"]) == ["Amina"]


def test_no_votes_no_winner(election):
    assert block(election)["winners"] == []


def multi_seat(election, picks=2):
    pos = election.positions[0]
    pos.max_selections = picks
    extra = Candidate(position_id=pos.id, name="Sofia", order_index=3)
    db.session.add(extra)
    db.session.commit()
    return pos, list(pos.candidates)


def test_multi_seat_top_n_win(election):
    pos, (a, d, s) = multi_seat(election, 2)
    add_votes(election, pos, a, 5)
    add_votes(election, pos, d, 4)
    add_votes(election, pos, s, 1)
    assert names(block(election)["winners"]) == ["Amina", "Daniel"]


def test_multi_seat_tie_on_the_last_seat(election):
    pos, (a, d, s) = multi_seat(election, 2)
    add_votes(election, pos, a, 5)
    add_votes(election, pos, d, 3)
    add_votes(election, pos, s, 3)
    b = block(election)
    assert names(b["winners"]) == ["Amina"] and names(b["tied"]) == ["Daniel", "Sofia"]


def test_multi_seat_resignation_pulls_up_the_next_candidate(election):
    pos, (a, d, s) = multi_seat(election, 2)
    add_votes(election, pos, a, 5)
    add_votes(election, pos, d, 4)
    add_votes(election, pos, s, 1)
    a.is_declined = True
    db.session.commit()
    assert names(block(election)["winners"]) == ["Daniel", "Sofia"]


def test_percentages_use_votes_for_single_seat_and_voters_for_multi_seat(election):
    pos, a, d = setup_votes(election, 3, 1)
    assert block(election)["candidates"][0]["pct"] == 75.0
    pos.max_selections = 2
    for i in range(4):
        make_voter(election, f"p{i}@example.com", key=f"30000{i}").used = True
    db.session.commit()
    assert block(election)["candidates"][0]["pct"] == 75.0 and block(election)["pct_of"] == "voters"


def test_same_person_winning_two_positions_is_flagged(election):
    p2 = Position(election_id=election.id, name="Treasurer", candidate_slots=2, order_index=2)
    db.session.add(p2)
    db.session.flush()
    twin = Candidate(position_id=p2.id, name="amina ", order_index=1)
    db.session.add(twin)
    db.session.commit()
    pos, a, d = setup_votes(election)
    add_votes(election, p2, twin, 2)
    conflicts = Election.winner_conflicts(election.summarize_results())
    assert len(conflicts) == 1 and conflicts[0]["positions"] == ["President", "Treasurer"]


# ---- admin actions -------------------------------------------------------------

def post(client, url, data, t):
    return client.post(url, data=dict(data, csrf_token=t), headers={"X-Requested-With": "fetch", "Accept": "application/json"})


def test_status_route_sets_flags_audits_and_clears_override(admin_client, election, token):
    pos, a, d = setup_votes(election)
    pos.winner_override_id = a.id
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/results")
    assert post(admin_client, f"/admin/candidates/{a.id}/status", {"state": "resigned"}, t).get_json()["ok"]
    db.session.refresh(a)
    db.session.refresh(pos)
    assert a.is_declined and not a.is_disqualified and pos.winner_override_id is None
    post(admin_client, f"/admin/candidates/{a.id}/status", {"state": "dismissed"}, t)
    db.session.refresh(a)
    assert a.is_disqualified and not a.is_declined
    post(admin_client, f"/admin/candidates/{a.id}/status", {"state": "active"}, t)
    db.session.refresh(a)
    assert a.is_eligible
    assert post(admin_client, f"/admin/candidates/{a.id}/status", {"state": "bogus"}, t).status_code == 400
    page = admin_client.get("/admin/settings/logs").get_data(as_text=True)
    assert "marked as resigned" in page and "marked as dismissed" in page


def test_status_can_change_after_voting_closed_and_after_publishing(admin_client, election, token):
    pos, a, d = setup_votes(election)
    election.end_time = datetime(2020, 1, 1)
    election.results_public, election.results_slug = True, "c"
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/results")
    assert post(admin_client, f"/admin/candidates/{a.id}/status", {"state": "resigned"}, t).get_json()["ok"]
    html = admin_client.application.test_client().get("/results/c").get_data(as_text=True)
    assert "Resigned" in html and "Elected" in html


def test_winner_override_rules(admin_client, election, token):
    pos, a, d = setup_votes(election)
    other = Candidate(position_id=Position(election_id=election.id, name="X", order_index=9).id if False else pos.id, name="Zed", order_index=5)
    db.session.add(other)
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/results")
    url = f"/admin/positions/{pos.id}/winner"
    assert post(admin_client, url, {"candidate_id": str(d.id)}, t).get_json()["ok"]
    db.session.refresh(pos)
    assert pos.winner_override_id == d.id
    assert post(admin_client, url, {"candidate_id": "99999"}, t).status_code == 400
    d.is_declined = True
    db.session.commit()
    assert post(admin_client, url, {"candidate_id": str(d.id)}, t).status_code == 409
    assert post(admin_client, url, {"candidate_id": ""}, t).get_json()["ok"]
    db.session.refresh(pos)
    assert pos.winner_override_id is None
    pos.max_selections = 2
    db.session.commit()
    assert post(admin_client, url, {"candidate_id": str(a.id)}, t).status_code == 409


def test_deleting_an_overridden_candidate_position_or_election_is_safe(admin_client, election, token):
    pos, a, d = setup_votes(election)
    t = token(f"/admin/elections/{election.id}/setup")
    pos.winner_override_id = a.id
    db.session.commit()
    db.session.query(Vote).delete()
    db.session.commit()
    assert post(admin_client, f"/admin/candidates/{a.id}/delete", {}, t).get_json()["ok"]
    db.session.refresh(pos)
    assert pos.winner_override_id is None
    pos.winner_override_id = d.id
    db.session.commit()
    assert post(admin_client, f"/admin/positions/{pos.id}/delete", {}, t).get_json()["ok"]
    p2 = Position(election_id=election.id, name="P2", order_index=7)
    db.session.add(p2)
    db.session.flush()
    c = Candidate(position_id=p2.id, name="Q", order_index=1)
    db.session.add(c)
    db.session.commit()
    p2.winner_override_id = c.id
    db.session.commit()
    assert post(admin_client, f"/admin/elections/{election.id}/delete", {}, t).get_json()["ok"]


def test_results_page_warns_about_double_winners_and_csv_has_status(admin_client, election):
    p2 = Position(election_id=election.id, name="Treasurer", candidate_slots=2, order_index=2)
    db.session.add(p2)
    db.session.flush()
    twin = Candidate(position_id=p2.id, name="Amina", order_index=1)
    db.session.add(twin)
    db.session.commit()
    pos, a, d = setup_votes(election)
    add_votes(election, p2, twin, 2)
    d.is_disqualified = True
    db.session.commit()
    html = admin_client.get(f"/admin/elections/{election.id}/results").get_data(as_text=True)
    assert "is winning President and Treasurer" in html and "Dismissed" in html
    csv_text = admin_client.get(f"/admin/elections/{election.id}/results.csv").get_data(as_text=True)
    assert "position,candidate,status,votes,percent,winner" in csv_text and "dismissed" in csv_text


def test_position_settings_clamp_selection_limit(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/setup")
    r = post(admin_client, f"/admin/elections/{election.id}/positions/create", {"name": "Reps", "candidate_slots": "4", "max_selections": "9"}, t)
    assert r.get_json()["ok"]
    reps = Position.query.filter_by(name="Reps").one()
    assert reps.candidate_slots == 4 and reps.max_selections == 4
    post(admin_client, f"/admin/positions/{reps.id}/update", {"name": "Reps", "candidate_slots": "2", "max_selections": "3"}, t)
    db.session.refresh(reps)
    assert reps.max_selections == 2
    post(admin_client, f"/admin/positions/{reps.id}/update", {"name": "Reps", "candidate_slots": "2", "max_selections": "0"}, t)
    db.session.refresh(reps)
    assert reps.max_selections == 1


def test_candidate_dialog_can_set_status(admin_client, election, token):
    t = token(f"/admin/elections/{election.id}/setup")
    cand = election.positions[0].candidates[0]
    post(admin_client, f"/admin/candidates/{cand.id}/update", {"name": cand.name, "status": "dismissed"}, t)
    db.session.refresh(cand)
    assert cand.is_disqualified


# ---- results email -----------------------------------------------------------------

def _capture():
    sent = []

    def fake(messages, config=None):
        sent.extend(messages)
        return [SendResult(True) for _ in messages]
    return sent, patch("app.admin.voters.send_messages", side_effect=fake)


def test_results_email_needs_published_results_then_respects_audience(admin_client, election, token):
    voted = make_voter(election, "yes@example.com", key="111111")
    voted.used = True
    make_voter(election, "no@example.com", key="222222")
    make_voter(election, "", key="333333").email = None
    db.session.commit()
    t = token(f"/admin/elections/{election.id}/results")
    url = f"/admin/elections/{election.id}/send"
    assert jpost(admin_client, url, {"kind": "results", "cursor": 0}, t).status_code == 409
    election.results_public, election.results_slug = True, "council-results"
    db.session.commit()
    sent, patcher = _capture()
    with patcher:
        d = jpost(admin_client, url, {"kind": "results", "cursor": 0, "audience": "voted"}, t).get_json()
        assert d["sent"] == 1 and d["done"]
        d = jpost(admin_client, url, {"kind": "results", "cursor": 0, "audience": "all"}, t).get_json()
        assert d["sent"] == 2
    assert [m.to for m in sent] == ["yes@example.com", "yes@example.com", "no@example.com"]
    assert "/results/council-results" in sent[0].text and "council" in sent[0].text and sent[0].subject == "Results for Council"
    assert VoterInvitation.query.filter(VoterInvitation.sent_at.isnot(None)).count() == 0


def test_results_template_is_editable_and_validated(admin_client, election, token):
    t = token("/admin/settings/email")
    base = {"email_provider": "smtp", "smtp_port": "25", "smtp_security": "none", "mail_sender": "a@b.co",
            "invite_subject": "i", "invite_body": "i", "reminder_subject": "r", "reminder_body": "r",
            "results_subject": "Final: {{ election_name }}", "results_body": "See {{ results_url }}"}
    assert post(admin_client, "/admin/settings/email", base, t).get_json()["ok"]
    from app.models import SystemSettings
    assert SystemSettings.query.first().results_subject == "Final: {{ election_name }}"
    base["results_body"] = "{{ broken"
    assert post(admin_client, "/admin/settings/email", base, t).status_code == 400


# ---- multi-select voting ---------------------------------------------------------------

def enter(client, key="123456"):
    return client.post("/", data={"election_code": "council", "voting_key": key, "csrf_token": csrf_token(client, "/")})


def three_candidate_election(election, picks=2):
    pos, ids = multi_seat(election, picks)
    return pos, [c.id for c in ids]


def test_multi_select_ballot_renders_checkboxes_and_enforces_the_limit(client, election):
    pos, ids = three_candidate_election(election, 2)
    make_voter(election)
    enter(client)
    html = client.get("/ballot").get_data(as_text=True)
    assert 'type="checkbox"' in html and "Choose up to 2" in html and 'data-max="2"' in html
    t = csrf_token(client, "/ballot")
    too_many = client.post("/ballot", data={f"position_{pos.id}": ids, "csrf_token": t})
    assert too_many.status_code == 200 and "choose up to 2" in too_many.get_data(as_text=True)
    assert client.get("/ballot/review").status_code in (302, 200)
    ok = client.post("/ballot", data={f"position_{pos.id}": ids[:2], "csrf_token": csrf_token(client, "/ballot")})
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/ballot/review")
    review = client.get("/ballot/review").get_data(as_text=True)
    assert "Amina" in review and "Daniel" in review and "Sofia" not in review


def test_multi_select_submit_records_one_vote_per_choice(client, election):
    pos, ids = three_candidate_election(election, 2)
    make_voter(election)
    enter(client)
    client.post("/ballot", data={f"position_{pos.id}": [ids[0], ids[2], ids[2]], "csrf_token": csrf_token(client, "/ballot")})
    client.post("/ballot/submit", data={"csrf_token": csrf_token(client, "/ballot/review")})
    assert sorted(v.candidate_id for v in Vote.query.all()) == sorted([ids[0], ids[2]])
    assert VoterInvitation.query.first().used


def test_single_choice_positions_still_use_radios_and_reject_two(client, election):
    pos = election.positions[0]
    make_voter(election)
    enter(client)
    assert 'type="radio"' in client.get("/ballot").get_data(as_text=True)
    ids = [c.id for c in pos.candidates]
    r = client.post("/ballot", data={f"position_{pos.id}": ids, "csrf_token": csrf_token(client, "/ballot")})
    assert r.status_code == 200 and "choose up to 1" in r.get_data(as_text=True)


def test_resigned_candidates_are_not_on_the_ballot_and_cannot_be_voted_for(client, election):
    pos = election.positions[0]
    a, d = pos.candidates
    a.is_declined = True
    db.session.commit()
    make_voter(election)
    enter(client)
    assert "Amina" not in client.get("/ballot").get_data(as_text=True)
    client.post("/ballot", data={f"position_{pos.id}": a.id, "csrf_token": csrf_token(client, "/ballot")})
    client.post("/ballot/submit", data={"csrf_token": csrf_token(client, "/ballot/review")})
    assert Vote.query.count() == 0


def test_old_single_id_drafts_in_a_live_session_still_submit(client, election):
    pos = election.positions[0]
    make_voter(election)
    enter(client)
    with client.session_transaction() as sess:
        sess["draft"] = {str(pos.id): pos.candidates[0].id}
    client.post("/ballot/submit", data={"csrf_token": csrf_token(client, "/ballot")})
    assert Vote.query.count() == 1


# ---- migrations -----------------------------------------------------------------------------

def _migrate_app(tmp_path):
    from app import create_app
    from config import TestConfig

    class Cfg(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'm.db'}"
        UPLOAD_FOLDER = str(tmp_path / "u")
    return create_app(Cfg)


def _columns(app, table):
    from sqlalchemy import inspect
    return {c["name"] for c in inspect(db.engine).get_columns(table)}


def test_migrations_from_scratch_and_from_the_2026_schema(tmp_path):
    from flask_migrate import upgrade
    from sqlalchemy import text
    app = _migrate_app(tmp_path)
    with app.app_context():
        upgrade(directory="migrations", revision="4c2f1a9f0b12")
        db.session.execute(text("INSERT INTO election (name, is_active, results_public) VALUES ('Old', 1, 0)"))
        db.session.execute(text("INSERT INTO position (election_id, name, candidate_slots, order_index) VALUES (1, 'P', 1, 1)"))
        db.session.execute(text("INSERT INTO candidate (position_id, name, order_index, is_declined, is_disqualified) VALUES (1, 'C', 1, 1, 0)"))
        db.session.commit()
        upgrade(directory="migrations")
        assert {"max_selections", "winner_override_id"} <= _columns(app, "position")
        assert {"email_provider", "resend_api_key", "results_subject", "results_body"} <= _columns(app, "system_settings")
        row = db.session.execute(text("SELECT p.max_selections, c.is_declined FROM position p JOIN candidate c ON c.position_id = p.id")).one()
        assert tuple(row) == (1, 1)
        assert Election.query.one().name == "Old"
