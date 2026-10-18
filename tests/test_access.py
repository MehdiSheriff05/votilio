import pytest

from app import db
from app.models import AdminGroup, AdminUser, AuditLog, Candidate, Election, Position, VoterInvitation
from tests.conftest import csrf_token, jpost, make_voter


def make_admin(name, super_admin=False):
    u = AdminUser(username=name, is_super_admin=super_admin)
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    return u


def sign_in(app, name):
    c = app.test_client()
    r = c.post("/admin/login", data={"username": name, "password": "password123", "csrf_token": csrf_token(c)})
    assert r.status_code == 302
    return c


def second_election():
    e = Election(name="Other", access_code="other", is_active=True)
    db.session.add(e)
    db.session.flush()
    p = Position(election_id=e.id, name="Chair", order_index=1)
    db.session.add(p)
    db.session.flush()
    c = Candidate(position_id=p.id, name="Zed", order_index=1)
    db.session.add(c)
    db.session.commit()
    return e, p, c


@pytest.fixture
def two(app, election):
    other, pos, cand = second_election()
    inv = make_voter(other, "o@example.com", key="909090")
    return election, other, pos, cand, inv


def page_status(client, path):
    return client.get(path).status_code


def test_regular_admin_sees_only_assigned_elections(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.commit()
    c = sign_in(app, "reg")
    html = c.get("/admin/").get_data(as_text=True)
    assert "Council" in html and "Other" not in html
    assert '"name": "Other"' not in html and "Other" not in c.get("/admin/").get_data(as_text=True)
    assert page_status(c, f"/admin/elections/{mine.id}/setup") == 200
    for path in (f"/admin/elections/{other.id}/setup", f"/admin/elections/{other.id}/voters", f"/admin/elections/{other.id}/results",
                 f"/admin/elections/{other.id}/voters.csv", f"/admin/elections/{other.id}/results.csv",
                 f"/admin/elections/{other.id}/voters/template.csv"):
        assert page_status(c, path) == 404, path


def test_every_kind_of_write_is_blocked_on_other_elections(app, two):
    mine, other, pos, cand, inv = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.commit()
    c = sign_in(app, "reg")
    t = csrf_token(c, f"/admin/elections/{mine.id}/setup")
    hdr = {"X-CSRFToken": t, "X-Requested-With": "fetch"}
    posts = [
        (f"/admin/elections/{other.id}/toggle", {}), (f"/admin/elections/{other.id}/positions/create", {"name": "X"}),
        (f"/admin/positions/{pos.id}/update", {"name": "Y"}), (f"/admin/positions/{pos.id}/delete", {}),
        (f"/admin/positions/{pos.id}/candidates/create", {"name": "Q"}), (f"/admin/candidates/{cand.id}/update", {"name": "Q"}),
        (f"/admin/candidates/{cand.id}/delete", {}), (f"/admin/candidates/{cand.id}/status", {"state": "resigned"}),
        (f"/admin/positions/{pos.id}/winner", {"candidate_id": str(cand.id)}),
        (f"/admin/invitations/{inv.id}/delete", {}), (f"/admin/invitations/{inv.id}/update", {"email": "z@example.com"}),
        (f"/admin/invitations/{inv.id}/send", {}), (f"/admin/elections/{other.id}/voters/add", {"email": "n@example.com"}),
        (f"/admin/elections/{other.id}/results/publish", {"state": "publish"}),
    ]
    for url, data in posts:
        r = c.post(url, data=dict(data, csrf_token=t), headers=hdr)
        assert r.status_code == 404, (url, r.status_code)
    for url, body in [(f"/admin/elections/{other.id}/send", {"kind": "invite"}), (f"/admin/elections/{other.id}/voters/import", {"rows": []}),
                      (f"/admin/elections/{other.id}/candidates/import/validate", {"rows": []}),
                      (f"/admin/elections/{other.id}/positions/reorder", {"ids": []}), (f"/admin/positions/{pos.id}/candidates/reorder", {"ids": []})]:
        assert jpost(c, url, body, t).status_code == 404, url
    assert c.get(f"/admin/invitations/{inv.id}/key").status_code == 404
    db.session.expire_all()
    assert Position.query.get(pos.id).name == "Chair" and Candidate.query.get(cand.id).is_eligible
    assert VoterInvitation.query.get(inv.id) is not None and Election.query.get(other.id).is_active


def test_access_through_a_group_and_losing_it(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    group = AdminGroup(name="Committee", members=[reg], elections=[other])
    db.session.add(group)
    db.session.commit()
    c = sign_in(app, "reg")
    assert page_status(c, f"/admin/elections/{other.id}/setup") == 200
    assert page_status(c, f"/admin/elections/{mine.id}/setup") == 404
    group.members.remove(reg)
    db.session.commit()
    assert page_status(c, f"/admin/elections/{other.id}/setup") == 404


def test_direct_and_group_access_combine_and_removal_is_exact(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.add(AdminGroup(name="G", members=[reg], elections=[mine, other]))
    db.session.commit()
    c = sign_in(app, "reg")
    assert "Other" in c.get("/admin/").get_data(as_text=True)
    mine.admins.remove(reg)
    db.session.commit()
    assert page_status(c, f"/admin/elections/{mine.id}/setup") == 200  # still reachable through the group


def test_super_admin_sees_everything(admin_client, two):
    mine, other, *_ = two
    html = admin_client.get("/admin/").get_data(as_text=True)
    assert "Council" in html and "Other" in html
    assert page_status(admin_client, f"/admin/elections/{other.id}/setup") == 200


def test_creator_keeps_their_new_election(app, election):
    reg = make_admin("reg")
    election.admins.append(reg)
    db.session.commit()
    c = sign_in(app, "reg")
    r = c.post("/admin/elections/create", data={"name": "Mine", "csrf_token": csrf_token(c, "/admin/elections/create")})
    assert r.status_code == 302
    created = Election.query.filter_by(name="Mine").one()
    assert page_status(c, f"/admin/elections/{created.id}/setup") == 200
    assert reg in created.admins


def test_access_pages_and_groups_are_super_admin_only(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.commit()
    c = sign_in(app, "reg")
    t = csrf_token(c, "/admin/")
    assert page_status(c, f"/admin/elections/{mine.id}/access") == 302
    assert page_status(c, "/admin/settings/groups") == 302
    for url, data in [(f"/admin/elections/{mine.id}/access/add", {"kind": "admin", "id": str(reg.id)}),
                      ("/admin/settings/groups/create", {"name": "Sneaky"})]:
        assert c.post(url, data=dict(data, csrf_token=t)).status_code == 302
    assert AdminGroup.query.count() == 0
    assert "Access" not in c.get(f"/admin/elections/{mine.id}/setup").get_data(as_text=True).split("ws-nav")[1].split("</nav>")[0]


def test_super_admin_can_manage_access_and_groups(admin_client, two, token):
    mine, other, *_ = two
    reg = make_admin("reg")
    t = token(f"/admin/elections/{mine.id}/access")
    h = {"X-Requested-With": "fetch", "Accept": "application/json"}
    assert admin_client.get(f"/admin/elections/{mine.id}/access").status_code == 200
    assert admin_client.post(f"/admin/elections/{mine.id}/access/add", data={"kind": "admin", "id": reg.id, "csrf_token": t}, headers=h).get_json()["ok"]
    assert reg in mine.admins
    assert admin_client.post(f"/admin/elections/{mine.id}/access/add", data={"kind": "admin", "id": 9999, "csrf_token": t}, headers=h).status_code == 404
    r = admin_client.post("/admin/settings/groups/create", data={"name": "Team", "members": [reg.id], "elections": [other.id], "csrf_token": t}, headers=h)
    assert r.get_json()["ok"]
    g = AdminGroup.query.one()
    assert g.members == [reg] and g.elections == [other]
    assert admin_client.post("/admin/settings/groups/create", data={"name": "team", "csrf_token": t}, headers=h).status_code == 409
    assert admin_client.post(f"/admin/settings/groups/{g.id}/update", data={"name": "Team 2", "csrf_token": t}, headers=h).get_json()["ok"]
    db.session.refresh(g)
    assert g.name == "Team 2" and g.members == [] and g.elections == []
    admin_client.post(f"/admin/elections/{mine.id}/access/remove", data={"kind": "admin", "id": reg.id, "csrf_token": t}, headers=h)
    db.session.refresh(mine)
    assert reg not in mine.admins
    assert admin_client.post(f"/admin/settings/groups/{g.id}/delete", data={"csrf_token": t}, headers=h).get_json()["ok"]
    assert AdminGroup.query.count() == 0
    html = admin_client.get("/admin/settings/groups").get_data(as_text=True)
    assert "No groups yet" in html


def test_super_admin_cannot_be_added_as_member_or_direct_admin(admin_client, election, token):
    sup = make_admin("boss2", True)
    t = token(f"/admin/elections/{election.id}/access")
    h = {"X-Requested-With": "fetch"}
    assert admin_client.post(f"/admin/elections/{election.id}/access/add", data={"kind": "admin", "id": sup.id, "csrf_token": t}, headers=h).status_code == 404
    admin_client.post("/admin/settings/groups/create", data={"name": "G", "members": [sup.id], "csrf_token": t}, headers=h)
    assert AdminGroup.query.one().members == []


def test_audit_log_is_limited_to_your_elections(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.add_all([AuditLog(event_type="a", message="visible-event", election_id=mine.id),
                        AuditLog(event_type="b", message="hidden-event", election_id=other.id),
                        AuditLog(event_type="c", message="global-event", election_id=None)])
    db.session.commit()
    html = sign_in(app, "reg").get("/admin/settings/logs").get_data(as_text=True)
    assert "visible-event" in html and "hidden-event" not in html and "global-event" not in html


def test_removing_access_or_deleting_the_admin_takes_effect_immediately(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.commit()
    c = sign_in(app, "reg")
    assert page_status(c, f"/admin/elections/{mine.id}/setup") == 200
    db.session.delete(reg)
    db.session.commit()
    r = c.get(f"/admin/elections/{mine.id}/setup")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_demoted_super_admin_loses_access_without_signing_in_again(app, two):
    mine, other, *_ = two
    boss = make_admin("boss2", True)
    c = sign_in(app, "boss2")
    assert page_status(c, f"/admin/elections/{other.id}/setup") == 200
    boss.is_super_admin = False
    db.session.commit()
    assert page_status(c, f"/admin/elections/{other.id}/setup") == 404
    assert page_status(c, "/admin/settings/email") == 302


def test_palette_lists_only_accessible_elections(app, two):
    mine, other, *_ = two
    reg = make_admin("reg")
    mine.admins.append(reg)
    db.session.commit()
    html = sign_in(app, "reg").get("/admin/").get_data(as_text=True)
    palette = html.split('id="palette-data">')[1].split("</script>")[0]
    assert "Council" in palette and "Other" not in palette


def test_deleting_an_election_or_group_cleans_up_access_rows(admin_client, two, token):
    mine, other, *_ = two
    reg = make_admin("reg")
    other.admins.append(reg)
    g = AdminGroup(name="G", members=[reg], elections=[other])
    db.session.add(g)
    db.session.commit()
    t = token(f"/admin/elections/{other.id}/setup")
    assert admin_client.post(f"/admin/elections/{other.id}/delete", data={"csrf_token": t}, headers={"X-Requested-With": "fetch"}).get_json()["ok"]
    db.session.expire_all()
    assert AdminGroup.query.one().elections == [] and reg.elections == []
    db.session.delete(reg)
    db.session.commit()
    assert AdminGroup.query.one().members == []


def test_migration_grants_existing_admins_every_existing_election(tmp_path):
    from flask_migrate import upgrade
    from sqlalchemy import text
    from app import create_app
    from config import TestConfig

    class Cfg(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'm.db'}"
        UPLOAD_FOLDER = str(tmp_path / "u")

    app = create_app(Cfg)
    with app.app_context():
        upgrade(directory="migrations", revision="f6d4c2b8e0a3")
        db.session.execute(text("INSERT INTO admin_user (username, password_hash, is_super_admin) VALUES ('boss','x',1),('reg','x',0)"))
        db.session.execute(text("INSERT INTO election (name, is_active, results_public) VALUES ('A',1,0),('B',1,0)"))
        db.session.commit()
        upgrade(directory="migrations")
        rows = db.session.execute(text("SELECT a.username, e.name FROM election_admin ea JOIN admin_user a ON a.id=ea.admin_id JOIN election e ON e.id=ea.election_id ORDER BY e.name")).all()
        assert [tuple(r) for r in rows] == [("reg", "A"), ("reg", "B")]
