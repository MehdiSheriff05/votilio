import click
from flask import Flask

from app import db
from app.models import AdminUser


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.argument("username")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option("--super/--regular", "is_super", default=True, show_default=True)
    def create_admin(username: str, password: str, is_super: bool) -> None:
        """Create an admin user."""
        username = username.strip()
        if not username or len(password) < 8:
            raise click.ClickException("Username required and password must be at least 8 characters.")
        if AdminUser.query.filter_by(username=username).first():
            raise click.ClickException(f"User '{username}' already exists.")
        user = AdminUser(username=username, is_super_admin=is_super)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {'super ' if is_super else ''}admin '{username}'.")

    @app.cli.command("bootstrap-admin")
    def bootstrap_admin() -> None:
        """Create the first super admin from ADMIN_USERNAME / ADMIN_PASSWORD if no admin exists."""
        username = app.config.get("BOOTSTRAP_ADMIN_USERNAME")
        password = app.config.get("BOOTSTRAP_ADMIN_PASSWORD")
        if AdminUser.query.first():
            return
        if not username or not password:
            click.echo("No admin exists. Set ADMIN_USERNAME and ADMIN_PASSWORD, or run: flask create-admin <name>")
            return
        if len(password) < 8:
            raise click.ClickException("ADMIN_PASSWORD must be at least 8 characters.")
        user = AdminUser(username=username, is_super_admin=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Bootstrapped super admin '{username}'. Remove ADMIN_PASSWORD from .env now.")
