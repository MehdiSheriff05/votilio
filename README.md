# Votilio

Votilio is a small web application for running online elections for clubs, societies, student bodies and similar organisations. An organiser sets up an election, loads the candidates and the voter list, and emails each voter a personal six-digit key. Voters sign in with their key, fill in a ballot and submit it. Ballots are stored without any reference to the voter.

It is a Flask application backed by Postgres and is meant to be run with Docker Compose on a single Linux server.

## Features

- Elections with positions, candidates (with photos and short bios) and a configurable voting window
- Voter list management, with per-voter status (not invited, invited, voted)
- CSV import for voters and for candidates, with a spreadsheet-style editor for fixing mistakes before importing
- Invitation and reminder emails, sent through Resend or through any SMTP server
- Ballot review step before a vote is submitted
- Live turnout and results for admins, and an optional public results page
- Admin accounts with two roles (admin and super admin) and an audit log
- Works on phones and laptops, with light and dark themes

## Requirements

- A Linux server with Docker Engine and the Docker Compose plugin
- A domain name pointing at the server, if you want HTTPS
- An email provider: a Resend account with a verified domain, or SMTP credentials

For development you also need Python 3.11 and Node.js 20.19 or newer (22 is recommended).

## Installation

### 1. Get the code and create your settings file

```bash
git clone <repository-url> votilio
cd votilio
cp .env.example .env
```

### 2. Fill in `.env`

The values you must set:

| Variable | Description |
| --- | --- |
| `FLASK_SECRET_KEY` | A random string of at least 32 characters. Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. The app will not start without it. |
| `POSTGRES_PASSWORD` | Password for the database. Use letters and digits only, since it is embedded in a connection URL. |
| `PUBLIC_BASE_URL` | The address voters use, for example `https://vote.example.com`, without a trailing slash. It is used for links in emails. |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | The first super admin account. It is created on first start if no admin exists. Delete `ADMIN_PASSWORD` from `.env` afterwards. |

Email settings can go in `.env` or be entered later under Settings > Email in the admin. See [Email](#email).

### 3. Start it

With HTTPS handled by the bundled Caddy container (set `DOMAIN` in `.env` and open ports 80 and 443):

```bash
docker compose --profile proxy up -d --build
```

Or, to put your own reverse proxy in front, start only the application. It listens on `127.0.0.1:8000`:

```bash
docker compose up -d --build
```

The first build takes a few minutes. When it finishes, `docker compose ps` should show the `web` service as healthy. Open your domain and sign in at `/admin`.

### Using nginx instead of Caddy

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 5m;
}
```

If you serve the site over plain HTTP (for testing on a local network only), set `SESSION_COOKIE_SECURE=false` in `.env`, otherwise browsers will not keep the login session.

## Configuration

Everything is read from environment variables, normally through `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `production` | Set to `development` for local work. |
| `DISPLAY_TIMEZONE` | `GMT+4` | Zone or offset used to show and enter dates. Can also be changed under Settings > General. |
| `EMAIL_PROVIDER` | (admin setting) | `resend` or `smtp`. When set, it overrides the admin setting. |
| `RESEND_API_KEY` | | Resend API key. Overrides the admin setting. |
| `MAIL_SENDER` | | The From address, for example `Votilio <vote@example.com>`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD` | | SMTP details. `SMTP_SECURITY` is `starttls`, `ssl` or `none`. |
| `SESSION_COOKIE_SECURE` | `true` in production | Set to `false` only for plain HTTP testing. |
| `TRUSTED_PROXY_COUNT` | `1` in production | Number of reverse proxies in front of the app. |
| `WEB_CONCURRENCY`, `WEB_THREADS` | `2`, `4` | Gunicorn workers and threads. |
| `MAX_IMPORT_ROWS` | `20000` | Row limit for a single CSV import. |
| `RATELIMIT_STORAGE_URI` | `memory://` | Use a Redis URL if you run more than one instance. |

### Email

Open Settings > Email as a super admin and choose a provider. The page has a "Send test" button that uses the values currently on screen, so you can check a configuration before saving it.

- **Resend:** create an API key, verify your sending domain in Resend, and use a sender address on that domain.
- **SMTP:** enter host, port, security mode (`starttls` normally on port 587, `ssl` on 465), username and password.

Passwords and API keys saved through the admin are encrypted in the database and are never displayed again. Values set in `.env` take precedence over the admin settings.

Invitation and reminder wording can be edited on the same page. The available placeholders are `election_name`, `election_code`, `voting_key`, `vote_url`, `recipient`, `recipient_email`, `opening_time` and `closing_time`.

## Running an election

1. **Create the election.** Give it a name, an optional voting window and a brand colour. If you leave the code blank, one is generated.
2. **Build the ballot.** On the Setup tab, add positions and their candidates, either one at a time or with Import CSV. Drag to change the order.
3. **Add voters.** On the Voters tab, import a CSV or add people individually.
4. **Send invitations.** Each voter receives the election code and their key. Anyone not yet invited can be handled in one pass, and reminders can be sent to people who have not voted.
5. **Watch turnout** on the Voters and Results tabs. Voting can be paused and resumed at any time.
6. **Publish results** if you want a public link. The Results tab can also export a CSV.

Voters who have no email address can still take part. A super admin can export all voting keys as a CSV to hand out in person, and any admin can look up a single voter's key.

## CSV imports

The import screen accepts a file, drag and drop, or pasted rows. Header names are matched loosely (`E-mail`, `Full name` and `Office` all work), column order does not matter, and extra columns are ignored. Templates can be downloaded from the import screen.

| Import | Columns | Notes |
| --- | --- | --- |
| Voters | `name` (optional), `email` (required) | Emails must be valid and unique, both within the file and against voters already on the list. |
| Candidates | `position`, `name` (required); `bio`, `photo_url` (optional) | `photo_url` must be an `http` or `https` link. A position's candidate limit is enforced. Enable "Create missing positions" to add positions found in the file. |

Rows with problems are highlighted in the editor and can be fixed in place or skipped. Imports are limited to 20,000 rows and 8 MB.

## Updating

```bash
git pull
docker compose up -d --build        # add --profile proxy if you use Caddy
```

Database migrations run automatically when the container starts. Take a backup first:

```bash
docker compose exec db pg_dump -U votilio votilio > backup.sql
```

Back up the `pgdata` and `uploads` volumes together, since candidate photos are stored in `uploads`.

### Upgrading from the 2025 version

- Keep your existing database volume. Set `POSTGRES_USER` and `POSTGRES_PASSWORD` in `.env` to the values your existing database was created with (the old compose file used `postgres` for both). Those settings only take effect when a database is first created, so a mismatch means the app cannot connect, not that data is lost.
- Elections, voters and votes carry over unchanged. Voting keys issued last year still work.
- Dates entered in the admin are now interpreted in the display timezone and stored as UTC. Existing stored times were already displayed as UTC, so nothing moves.
- Candidate photos lived inside the old container. Copy them into the new `uploads` volume if you still have them.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

export APP_ENV=development
export FLASK_SECRET_KEY=any-string-of-at-least-32-characters-here
export DATABASE_URL=sqlite:///dev.db

flask --app wsgi db upgrade
flask --app wsgi create-admin admin
(cd frontend && npm ci && npm run build)
flask --app wsgi run
```

The site is then at http://localhost:5000 and the admin at `/admin`. Outgoing email needs a server to talk to. For local testing, `python -m aiosmtpd -n -l 127.0.0.1:1025` runs a throwaway one that prints messages to the terminal; point Settings > Email at it with security set to `none`.

Run the tests with:

```bash
pytest                              # backend
(cd frontend && npm test)           # CSV validation and parsing
```

### Project layout

```
app/
  admin/        admin routes: elections, voters, CSV import, settings
  public/       voter-facing routes
  mailer/       email providers (Resend, SMTP) and message rendering
  templates/    Jinja templates
  static/       CSS, JavaScript and fonts
  imports.py    CSV validation rules (mirrored in the browser editor)
frontend/       source for the CSV editor (Svelte), built into app/static/dist
migrations/     Alembic migrations
tests/          backend tests
```

The CSV editor is the only part that needs a build step. Everything else is server-rendered templates with a small amount of plain JavaScript.

## Security notes

- Sign-in and voting-key entry are rate limited. Only failed voter attempts count, so a group of voters sharing one network address are not locked out by each other.
- Ballots are stored with no link to the voter. The audit log does record which voters submitted a ballot and when, so restrict log access if timing correlation is a concern in your setting.
- Keep `FLASK_SECRET_KEY` stable. Changing it signs everyone out and makes saved email credentials unreadable (enter them again in Settings > Email). Voting keys keep working.
- Treat the voting key export as sensitive.
