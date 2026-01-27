# Votilio
Votilio is a Flask application for running online elections with anonymous ballots, hashed voting keys, and a lightweight admin dashboard.

## Features
- Snappy admin dashboard to manage elections, positions, candidates, and invitations.
- Voter flow with 6-digit keys, aggregated statistics only, and anonymous vote storage.
- Theme controls per election for branded ballots and public result pages.
- Publish-ready results: highlight winners, toggle a public link, and share the URL after the contest ends.
- SMTP settings editable from the GUI (super admin only) so each tenant or environment can plug in their mail provider without redeploying.
- Bulk + manual key generation, with one-time visibility into new identifiers while keeping hashes stored server-side.
- Dockerfile + docker-compose for containerized deployments.

## Install on Linux (Docker only)
Commands below assume Ubuntu 22.04 and root SSH access. Adjust paths if you use a different distro.

### 1. System packages
```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl gnupg lsb-release git nginx certbot python3-certbot-nginx
```

### 2. Install Docker + Compose plugin
```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### 3. Clone and configure
```bash
cd /root
git clone https://github.com/MehdiSheriff05/votilio.git
cd votilio
cp .env.example .env
nano .env
```

Minimum `.env`:
```
FLASK_SECRET_KEY=change-this-to-a-long-random-string
DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/votilio
MAIL_SENDER=no-reply@yourdomain.com
```

### 4. Nginx reverse proxy + HTTPS
```bash
nano /etc/nginx/sites-available/votilio
```
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
```bash
ln -s /etc/nginx/sites-available/votilio /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d example.com -d www.example.com
```

### 5. Start the containers
```bash
cd /root/votilio
docker compose up --build -d
```

### 6. Create the first admin user
```bash
docker compose exec web flask shell
```
```python
from app import db
from app.models import AdminUser
admin = AdminUser(username="admin", is_super_admin=True)
admin.set_password("change-me")
db.session.add(admin); db.session.commit()
exit()
```

### 7. Update workflow
```bash
cd /root/votilio
git pull
docker compose build
docker compose up -d
docker compose exec web flask db upgrade
```

### 8. Backups
```bash
docker compose exec db pg_dump -U postgres votilio > backup.sql
```
