import uuid

from db import db
from journalist_app import create_app
from sqlalchemy import text

from .helpers import random_datetime


class UpgradeTester:
    """Verify that journalist_login_attempt rows are migrated from
    journalist_id to username."""

    def __init__(self, config):
        self.config = config
        self.app = create_app(config)

    def load_data(self):
        with self.app.app_context():
            # Create a journalist
            db.engine.execute(
                text(
                    """\
                INSERT INTO journalists (uuid, username, passphrase_hash, otp_secret)
                VALUES (:uuid, :username, :passphrase_hash, :otp_secret)
                """
                ),
                uuid=str(uuid.uuid4()),
                username="testuser",
                passphrase_hash="dummy",
                otp_secret="A" * 32,
            )
            journalist = db.engine.execute(
                text("SELECT id FROM journalists WHERE username='testuser'")
            ).first()
            # Insert a login attempt for that journalist
            db.engine.execute(
                text(
                    """\
                INSERT INTO journalist_login_attempt (timestamp, journalist_id)
                VALUES (:timestamp, :journalist_id)
                """
                ),
                timestamp=random_datetime(nullable=False),
                journalist_id=journalist[0],
            )

    def check_upgrade(self):
        with self.app.app_context():
            attempts = db.engine.execute(text("SELECT * FROM journalist_login_attempt")).fetchall()
            assert len(attempts) == 1
            # Verify the username column is populated
            attempt = attempts[0]
            assert attempt.username == "testuser"
            # Verify journalist_id column no longer exists
            assert not hasattr(attempt, "journalist_id")


class DowngradeTester:
    """Verify that journalist_login_attempt rows are migrated back from
    username to journalist_id."""

    def __init__(self, config):
        self.config = config
        self.app = create_app(config)

    def load_data(self):
        with self.app.app_context():
            # Create a journalist
            db.engine.execute(
                text(
                    """\
                INSERT INTO journalists (uuid, username, passphrase_hash, otp_secret)
                VALUES (:uuid, :username, :passphrase_hash, :otp_secret)
                """
                ),
                uuid=str(uuid.uuid4()),
                username="testuser2",
                passphrase_hash="dummy",
                otp_secret="B" * 32,
            )
            # Insert a login attempt with username
            db.engine.execute(
                text(
                    """\
                INSERT INTO journalist_login_attempt (timestamp, username)
                VALUES (:timestamp, :username)
                """
                ),
                timestamp=random_datetime(nullable=False),
                username="testuser2",
            )

    def check_downgrade(self):
        with self.app.app_context():
            attempts = db.engine.execute(text("SELECT * FROM journalist_login_attempt")).fetchall()
            assert len(attempts) == 1
            attempt = attempts[0]
            # Verify journalist_id column is restored
            assert attempt.journalist_id is not None
            # Verify username column no longer exists
            assert not hasattr(attempt, "username")
