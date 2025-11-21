# Votilio
Votilio is a Flask application for running online elections with anonymous ballots, hashed voting keys, and a lightweight admin dashboard.

## Features
- Snappy admin dashboard to manage elections, positions, candidates, and invitations.
- Voter flow with 6-digit keys, aggregated statistics only, and anonymous vote storage.
- Theme controls per election for branded ballots and public result pages.
- Publish-ready results: highlight winners, toggle a public public link, and share the URL after the contest ends.
- SMTP settings fully editable from the GUI (super admin only) so each tenant or environment can plug in their mail provider without redeploying.
- PostgreSQL (via docker-compose) or SQLite for quick local prototyping.
- Bulk + manual key generation, with one-time visibility into new identifiers while keeping hashes stored server-side.
- Dockerfile + docker-compose for containerized deployments.

## Getting started (local dev)
1. **Install dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configure environment**
   ```bash
   cp .env.example .env
   export FLASK_APP=wsgi.py
   export FLASK_ENV=development
   ```
   - If you prefer SQLite locally, override `DATABASE_URL=sqlite:///votilio.db` in `.env`.

3. **Run the migrations**
   ```bash
   flask db upgrade
   ```
4. **Create an initial admin user**
   ```bash
   flask shell
   >>> from app import db
   >>> from app.models import AdminUser
   >>> admin = AdminUser(username="admin")
   >>> admin.set_password("change-me")
   >>> db.session.add(admin)
   >>> db.session.commit()
   ```
5. **Run the dev server**
   ```bash
   flask run
   ```

## Running with Docker
1. Copy environment template and adjust values:
   ```bash
   cp .env.example .env
   ```
2. Build and start the stack:
   ```bash
   docker-compose up --build
   ```
   The web container waits for Postgres, runs `flask db upgrade`, then launches Gunicorn automatically.
3. Create the initial admin user:
   ```bash
   docker-compose exec web flask shell
   ```

The Flask app listens on `http://localhost:8000` and Postgres on `localhost:5432` 
## Tests
An example pytest lives in `tests/` to illustrate key generation expectations. Run with:
```bash
pytest
```
