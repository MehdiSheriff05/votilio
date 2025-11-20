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

    def summarize_results(self):
        summary = []
        for position in sorted(self.positions, key=lambda p: p.order_index):
            candidate_counts = []
            max_votes = 0
            total_votes = 0
            for candidate in position.candidates:
                count = Vote.query.filter_by(
                    election_id=self.id,
                    position_id=position.id,
                    candidate_id=candidate.id,
                ).count()
                candidate_counts.append({
                    'candidate': candidate,
                    'count': count,
                })
                total_votes += count
                if count > max_votes:
                    max_votes = count
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

    candidates = db.relationship('Candidate', backref='position', lazy=True, cascade='all, delete-orphan')


class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    position_id = db.Column(db.Integer, db.ForeignKey('position.id'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)


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

    def set_key(self, raw_key: str) -> None:
        self.voting_key_hash = generate_password_hash(raw_key)

    def check_key(self, raw_key: str) -> bool:
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
    invite_body = db.Column(db.Text, nullable=False, default="You are invited to vote in '{{ election_name }}'.\n\nKey: {{ voting_key }}\nVote link: {{ vote_url }}\n")
    reminder_subject = db.Column(db.String(255), nullable=False, default="Reminder: vote in {{ election_name }}")
    reminder_body = db.Column(db.Text, nullable=False, default="Friendly reminder to vote in '{{ election_name }}'. Use key {{ voting_key }} at {{ vote_url }}.")

    @classmethod
    def get_or_create(cls, app=None):
        instance = cls.query.first()
        if instance:
            return instance
        from flask import current_app

        app_obj = app or current_app
        instance = cls(
            smtp_host=app_obj.config.get("SMTP_HOST", "localhost"),
            smtp_port=app_obj.config.get("SMTP_PORT", 1025),
            smtp_user=app_obj.config.get("SMTP_USER"),
            smtp_password=app_obj.config.get("SMTP_PASSWORD"),
            mail_sender=app_obj.config.get("MAIL_SENDER", "no-reply@votilio.local"),
            invite_subject="Your Votilio key for {{ election_name }}",
            invite_body="You are invited to vote in '{{ election_name }}'.\n\nKey: {{ voting_key }}\nVote link: {{ vote_url }}\n",
            reminder_subject="Reminder: vote in {{ election_name }}",
            reminder_body="Friendly reminder to vote in '{{ election_name }}'. Use key {{ voting_key }} at {{ vote_url }}.",
        )
        db.session.add(instance)
        db.session.commit()
        return instance
