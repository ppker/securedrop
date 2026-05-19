"""add username to journalist_login_attempt

Revision ID: b7f98cfd6a71
Revises: 17c559a7a685
Create Date: 2026-02-10 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7f98cfd6a71"
down_revision = "17c559a7a685"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("PRAGMA legacy_alter_table=ON"))

    # Rename old table
    op.rename_table("journalist_login_attempt", "journalist_login_attempt_tmp")

    # Create new table with username column instead of journalist_id FK
    op.create_table(
        "journalist_login_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Migrate data: join with journalists to get usernames
    conn.execute(
        sa.text(
            """
            INSERT INTO journalist_login_attempt (id, timestamp, username)
            SELECT jla.id, jla.timestamp, j.username
            FROM journalist_login_attempt_tmp jla
            JOIN journalists j ON jla.journalist_id = j.id
            """
        )
    )

    # Drop old table
    op.drop_table("journalist_login_attempt_tmp")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("PRAGMA legacy_alter_table=ON"))

    # Rename new table
    op.rename_table("journalist_login_attempt", "journalist_login_attempt_tmp")

    # Recreate old table with journalist_id FK
    op.create_table(
        "journalist_login_attempt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("journalist_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["journalist_id"], ["journalists.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Migrate data back: join with journalists to get IDs from usernames
    conn.execute(
        sa.text(
            """
            INSERT INTO journalist_login_attempt (id, timestamp, journalist_id)
            SELECT jla.id, jla.timestamp, j.id
            FROM journalist_login_attempt_tmp jla
            JOIN journalists j ON jla.username = j.username
            """
        )
    )

    # Drop temp table
    op.drop_table("journalist_login_attempt_tmp")
