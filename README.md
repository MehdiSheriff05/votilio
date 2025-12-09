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

## Deploying with Docker (Ubuntu server example)
Follow these explicit steps if you are new to server management. Commands assume Ubuntu 22.04 and that you start with root SSH access.

### 1. Create a deploy user and secure SSH
```bash
adduser deploy                        # set a strong password when prompted
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
nano /home/deploy/.ssh/authorized_keys
```
Paste your **public** SSH key (from `~/.ssh/id_ed25519.pub`) into that file, save with `Ctrl+O`, exit with `Ctrl+X`, then:
```bash
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```
Edit `/etc/ssh/sshd_config`:
```bash
nano /etc/ssh/sshd_config
```
Set:
```
PermitRootLogin no
PasswordAuthentication no
```
Save, exit, and restart SSH:
```bash
systemctl restart sshd
```
Reconnect as the new user:
```bash
ssh deploy@YOUR_SERVER_IP
```

### 2. Update packages + enable firewall
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ufw fail2ban
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow http
sudo ufw allow https
sudo ufw enable
```

### 3. Install Docker, compose plugin, Git, and nginx/certbot
```bash
sudo apt install -y ca-certificates curl gnupg lsb-release git nginx certbot python3-certbot-nginx
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

### 4. Clone the project into `/home/deploy/votilio`
```bash
cd /home/deploy
git clone https://github.com/MehdiSheriff05/votilio.git
cd votilio
cp .env.example .env
nano .env
```
Inside `.env`, paste something like:
```
FLASK_SECRET_KEY=change-this-to-a-long-random-string
DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/votilio
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
MAIL_SENDER=no-reply@votilio.local
```

### 5. Configure nginx reverse proxy + HTTPS
Create the site file:
```bash
sudo nano /etc/nginx/sites-available/votilio
```
Paste:
```
server {
    listen 80;
    server_name example.com www.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
Enable it:
```bash
sudo ln -s /etc/nginx/sites-available/votilio /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d example.com -d www.example.com
```
(Replace `example.com` with your domain.)

### 6. Start the containers
```bash
cd /home/deploy/votilio
docker compose up --build -d
```
Tail logs if desired:
```bash
docker compose logs -f
```

### 7. Create the first admin user
```bash
docker compose exec web flask shell
>>> from app import db
>>> from app.models import AdminUser
>>> admin = AdminUser(username="admin")
>>> admin.set_password("change-me")
>>> db.session.add(admin); db.session.commit()
>>> exit()
```

### 8. Test & maintain
- Visit `https://example.com` and `https://example.com/admin`.
- Update workflow:
  ```bash
  cd /home/deploy/votilio
  git pull
  docker compose build
  docker compose up -d
  docker compose exec web flask db upgrade
  ```
- Back up Postgres: `docker compose exec db pg_dump -U postgres votilio > backup.sql`.
## Tests
An example pytest lives in `tests/` to illustrate key generation expectations. Run with:
```bash
pytest
```
