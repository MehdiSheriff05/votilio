import hashlib
import hmac
from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash, generate_password_hash

from app import db


class AdminUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Election(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    access_code = db.Column(db.String(32), unique=True, nullable=True)
    results_public = db.Column(db.Boolean, default=False, nullable=False)
    results_slug = db.Column(db.String(64), unique=True, nullable=True)
    theme_primary = db.Column(db.String(7), nullable=True)
    theme_secondary = db.Column(db.String(7), nullable=True)
    theme_accent = db.Column(db.String(7), nullable=True)

    positions = db.relationship('Position', backref='election', lazy=True, cascade='all, delete-orphan')
    invitations = db.relationship('VoterInvitation', backref='election', lazy=True, cascade='all, delete-orphan')

    def is_open(self) -> bool:
        now = datetime.utcnow()
        if not self.is_active:
            return False
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return True

    def status(self) -> str:
        now = datetime.utcnow()
        if not self.is_active:
            return "paused"
        if self.start_time and now < self.start_time:
            return "scheduled"
        if self.end_time and now > self.end_time:
            return "closed"
        return "live"

    def summarize_results(self):
        counts = dict(
            db.session.query(Vote.candidate_id, db.func.count(Vote.id))
            .filter(Vote.election_id == self.id)
            .group_by(Vote.candidate_id)
            .all()
        )
        summary = []
        for position in sorted(self.positions, key=lambda p: (p.order_index, p.id)):
            candidate_counts = []
            max_votes = 0
            total_votes = 0
            for candidate in position.candidates:
                count = counts.get(candidate.id, 0)
                candidate_counts.append({'candidate': candidate, 'count': count})
                total_votes += count
                max_votes = max(max_votes, count)
            winners = [item['candidate'] for item in candidate_counts if item['count'] == max_votes and max_votes > 0]
            summary.append({
                'position': position,
                'candidates': candidate_counts,
                'winners': winners,
                'max_votes': max_votes,
                'total_votes': total_votes,
            })
        return summary


class Position(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey('election.id'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    candidate_slots = db.Column(db.Integer, default=1, nullable=False)
    order_index = db.Column(db.Integer, nullable=False, default=0)

    candidates = db.relationship('Candidate', backref='position', lazy=True, cascade='all, delete-orphan',
                                 order_by='(Candidate.order_index, Candidate.id)')


class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)
    order_index = db.Column(db.Integer, nullable=False, default=0, server_default="0")


class VoterInvitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey('election.id'), nullable=False)
    name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    voting_key_hash = db.Column(db.String(255), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    used = db.Column(db.Boolean, default=False, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    reminder_sent_at = db.Column(db.DateTime, nullable=True)
    last_generated_key = db.Column(db.String(64), nullable=True)

    HMAC_PREFIX = "hmac$"

    @classmethod
    def hash_key(cls, election_id: int, raw_key: str) -> str:
        """Keyed, deterministic digest so keys can be looked up directly instead of scanning slow hashes."""
        from flask import current_app
        secret = current_app.config["SECRET_KEY"].encode()
        digest = hmac.new(secret, f"{election_id}:{raw_key}".encode(), hashlib.sha256).hexdigest()
        return cls.HMAC_PREFIX + digest

    def set_key(self, raw_key: str) -> None:
        self.voting_key_hash = self.hash_key(self.election_id, raw_key)

    def check_key(self, raw_key: str) -> bool:
        if self.voting_key_hash.startswith(self.HMAC_PREFIX):
            return hmac.compare_digest(self.voting_key_hash, self.hash_key(self.election_id, raw_key))
        return check_password_hash(self.voting_key_hash, raw_key)


class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey('election.id'), nullable=False)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidate.id'), nullable=False)
    cast_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Important: No voter identifiers are stored here to preserve anonymity.
    election = db.relationship('Election', backref=db.backref('votes', lazy=True))
    position = db.relationship('Position')
    candidate = db.relationship('Candidate')


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(64), nullable=False)
    message = db.Column(db.Text, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('admin_user.id'), nullable=True)
    election_id = db.Column(db.Integer, db.ForeignKey('election.id'), nullable=True)
    invitation_id = db.Column(db.Integer, db.ForeignKey('voter_invitation.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    admin = db.relationship('AdminUser', backref=db.backref('audit_logs', lazy=True))
    election = db.relationship('Election', backref=db.backref('audit_logs', lazy=True))
    invitation = db.relationship('VoterInvitation', backref=db.backref('audit_logs', lazy=True))


class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    smtp_host = db.Column(db.String(255), nullable=False, default="localhost")
    smtp_port = db.Column(db.Integer, nullable=False, default=1025)
    smtp_user = db.Column(db.String(255), nullable=True)
    smtp_password = db.Column(db.String(255), nullable=True)
    mail_sender = db.Column(db.String(255), nullable=False, default="no-reply@votilio.local")
    invite_subject = db.Column(db.String(255), nullable=False, default="Your Votilio key for {{ election_name }}")
    invite_body = db.Column(db.Text, nullable=False, default="You are invited to vote in '{{ election_name }}'.\n\nElection code: {{ election_code }}\nVoting key: {{ voting_key }}\n\nVote here: {{ vote_url }}\n")
    reminder_subject = db.Column(db.String(255), nullable=False, default="Reminder: vote in {{ election_name }}")
    reminder_body = db.Column(db.Text, nullable=False, default="Friendly reminder to vote in '{{ election_name }}'. Election code: {{ election_code }}, voting key: {{ voting_key }}. Vote at {{ vote_url }}.")
    timezone_name = db.Column(db.String(128), nullable=False, default="UTC")
    email_provider = db.Column(db.String(16), nullable=False, default="smtp", server_default="smtp")
    smtp_security = db.Column(db.String(16), nullable=False, default="starttls", server_default="starttls")
    resend_api_key = db.Column(db.String(512), nullable=True)

    @property
    def smtp_password_plain(self) -> str:
        from app.secrets_box import decrypt
        return decrypt(self.smtp_password)

    @smtp_password_plain.setter
    def smtp_password_plain(self, value) -> None:
        from app.secrets_box import encrypt
        self.smtp_password = encrypt(value)

    @property
    def resend_api_key_plain(self) -> str:
        from app.secrets_box import decrypt
        return decrypt(self.resend_api_key)

    @resend_api_key_plain.setter
    def resend_api_key_plain(self, value) -> None:
        from app.secrets_box import encrypt
        self.resend_api_key = encrypt(value)

    @classmethod
    def get_or_create(cls, app=None):
        instance = cls.query.first()
        if instance:
            return instance
        from flask import current_app

        app_obj = app or current_app
        instance = cls(
            smtp_host=app_obj.config.get("SMTP_HOST") or "",
            smtp_port=app_obj.config.get("SMTP_PORT") or 587,
            smtp_user=app_obj.config.get("SMTP_USER") or None,
            mail_sender=app_obj.config.get("MAIL_SENDER") or "no-reply@votilio.local",
            email_provider=app_obj.config.get("EMAIL_PROVIDER") or "smtp",
            smtp_security=app_obj.config.get("SMTP_SECURITY") or "starttls",
            invite_subject="Your Votilio key for {{ election_name }}",
            invite_body="You are invited to vote in '{{ election_name }}'.\n\nElection code: {{ election_code }}\nVoting key: {{ voting_key }}\n\nVote here: {{ vote_url }}\n",
            reminder_subject="Reminder: vote in {{ election_name }}",
            reminder_body="Friendly reminder to vote in '{{ election_name }}'. Election code: {{ election_code }}, voting key: {{ voting_key }}. Vote at {{ vote_url }}.",
            timezone_name=app_obj.config.get("DISPLAY_TIMEZONE", "UTC"),
        )
        instance.smtp_password_plain = app_obj.config.get("SMTP_PASSWORD") or None
        db.session.add(instance)
        db.session.commit()
        return instance
