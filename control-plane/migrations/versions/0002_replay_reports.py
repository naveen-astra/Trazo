"""Add replay_reports: the fidelity report `trazo verify` computes.

Mirrors trazo_server.store.models.replay_reports (hand-kept in sync, same
convention as 0001_baseline.py).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replay_reports",
        sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), primary_key=True),
        sa.Column("boundary_fidelity", sa.Float, nullable=False),
        sa.Column("state_fidelity", sa.Float, nullable=False),
        sa.Column("matched", sa.Integer, nullable=False),
        sa.Column("reordered", sa.Integer, nullable=False),
        sa.Column(
            "divergences",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("replay_overhead", sa.Float),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("replay_reports")
