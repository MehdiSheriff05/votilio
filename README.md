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
1. **Ensure Docker Engine + Compose plugin are installed**
   - macOS/Windows: install Docker Desktop.
   - Linux (Ubuntu example):
     ```bash
     sudo apt update && sudo apt install -y ca-certificates curl gnupg
     curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
     echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list
     sudo apt update
     sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
     sudo usermod -aG docker $USER && newgrp docker
     ```
2. **Copy environment template and adjust values**
   ```bash
   cp .env.example .env
   ```
   Set `FLASK_SECRET_KEY`, SMTP credentials, etc. The default `DATABASE_URL` already points to the bundled Postgres container.
3. **Build and start the stack**
   ```bash
   docker compose up --build -d
   ```
   (Use `docker-compose` if your CLI doesn’t support the space-separated syntax.) The entrypoint waits for Postgres, applies migrations, then starts Gunicorn.
4. **Create the initial admin user**
   ```bash
   docker compose exec web flask shell
   >>> from app import db
   >>> from app.models import AdminUser
   >>> admin = AdminUser(username="admin")
   >>> admin.set_password("change-me")
   >>> db.session.add(admin)
   >>> db.session.commit()
   >>> exit()
   ```

The Flask app listens on `http://localhost:8000` and Postgres on `localhost:5432`.

## Deploying with Docker on a VPS
1. **Provision & secure your server**
   - Create a non-root sudo user, add your SSH public key, disable root/password SSH.
   - Update packages and enable a firewall (Ubuntu example):
     ```bash
     sudo apt update && sudo apt upgrade -y
     sudo apt install -y ufw
     sudo ufw allow OpenSSH
     sudo ufw allow http
     sudo ufw allow https
     sudo ufw enable
     ```
2. **Install Docker + compose plugin** (same commands as in the local section).
3. **Clone the repo & configure environment**
   ```bash
   git clone https://github.com/MehdiSheriff05/votilio.git
   cd votilio
   cp .env.example .env
   nano .env  # set FLASK_SECRET_KEY, SMTP settings (or configure later via GUI)
   ```
4. **Configure nginx + HTTPS**
   - Install nginx + certbot: `sudo apt install -y nginx certbot python3-certbot-nginx`
   - Create `/etc/nginx/sites-available/votilio` proxying to `http://127.0.0.1:8000`, enable it, test, then obtain certificates: `sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com`.
5. **Build and run the stack**
   ```bash
   docker compose up --build -d
   ```
6. **Seed the first admin**
   ```bash
   docker compose exec web flask shell
   >>> from app import db
   >>> from app.models import AdminUser
   >>> admin = AdminUser(username="admin")
   >>> admin.set_password("change-me")
   >>> db.session.add(admin); db.session.commit()
   >>> exit()
   ```
7. **Test & maintain**
   - Visit `https://yourdomain.com` and `/admin` to verify.
   - For updates: `git pull`, `docker compose build`, `docker compose up -d`, then `docker compose exec web flask db upgrade`.
   - Back up Postgres regularly (`docker compose exec db pg_dump -U postgres votilio > backup.sql`).
## Tests
An example pytest lives in `tests/` to illustrate key generation expectations. Run with:
```bash
pytest
```
