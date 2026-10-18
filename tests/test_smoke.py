from tests.conftest import make_voter


def test_public_and_login_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/admin/login").status_code == 200
    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/nope").status_code == 404


def test_admin_requires_login(client, election):
    r = client.get(f"/admin/elections/{election.id}/setup")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_every_admin_page_renders(admin_client, election):
    make_voter(election)
    e = election.id
    for path in ["/admin/", "/admin/elections/create", f"/admin/elections/{e}/setup", f"/admin/elections/{e}/voters",
                 f"/admin/elections/{e}/voters?status=voted&q=vee", f"/admin/elections/{e}/results",
                 "/admin/settings/email", "/admin/settings/general", "/admin/settings/admins", "/admin/settings/logs",
                 f"/admin/elections/{e}/voters.csv", f"/admin/elections/{e}/voter-keys.csv",
                 f"/admin/elections/{e}/voters/template.csv", f"/admin/elections/{e}/candidates/template.csv",
                 f"/admin/elections/{e}/results.csv"]:
        r = admin_client.get(path)
        assert r.status_code == 200, (path, r.status_code)


def test_no_form_control_shadows_the_form_action_property(admin_client, election):
    """A control named "action" (or "method") makes form.action return the element in browsers and breaks fetch()."""
    import re
    e = election.id
    for path in ["/admin/", f"/admin/elections/{e}/setup", f"/admin/elections/{e}/voters", f"/admin/elections/{e}/results",
                 "/admin/settings/email", "/admin/settings/admins", "/admin/settings/logs", "/", "/admin/login"]:
        html = admin_client.get(path).get_data(as_text=True)
        assert not re.search(r'<(input|select|button|textarea)[^>]*\bname="(action|method|target|enctype)"', html), path
