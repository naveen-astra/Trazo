"""Baseline schema: projects, runs, events, blobs, detections, policy_decisions.

Implements DATABASE.md §2 exactly; mirrors trazo_server.store.models
(hand-kept in sync — see that module's docstring).

Revision ID: 0001
Revises:
Create Date: 2026-07-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column(
            "project_id",
            sa.Text,
            sa.ForeignKey("projects.project_id"),
            nullable=False,
        ),
        sa.Column("framework", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "tags",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "totals",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "runs_project_started", "runs", ["project_id", sa.text("started_at DESC")]
    )
    op.create_index(
        "runs_status",
        "runs",
        ["status"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "events",
        sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_id", sa.Text),
        sa.Column("agent_id", sa.Text),
        sa.Column("fingerprint", sa.Text),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "blobs",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("run_id", "seq"),
    )
    op.create_index("events_kind", "events", ["run_id", "kind", "seq"])
    op.create_index(
        "events_fingerprint",
        "events",
        ["fingerprint"],
        postgresql_where=sa.text("fingerprint IS NOT NULL"),
    )
    op.create_index(
        "events_payload_gin",
        "events",
        ["payload"],
        postgresql_using="gin",
        postgresql_ops={"payload": "jsonb_path_ops"},
    )

    op.create_table(
        "blobs",
        sa.Column("sha256", sa.Text, primary_key=True),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column(
            "content_type",
            sa.Text,
            nullable=False,
            server_default="application/json",
        ),
        sa.Column("storage", sa.Text, nullable=False),
        sa.Column("ref", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "detections",
        sa.Column("detection_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("detector", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", postgresql.JSONB, nullable=False),
        sa.Column("details", postgresql.JSONB, nullable=False),
    )
    op.create_index("detections_run", "detections", ["run_id"])

    op.create_table(
        "policy_decisions",
        sa.Column("decision_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("policy_id", sa.Text, nullable=False),
        sa.Column("action_kind", sa.Text, nullable=False),
        sa.Column("action_fp", sa.Text, nullable=False),
        sa.Column("decision", sa.Text, nullable=False),
        sa.Column("mode", sa.Text, nullable=False),
        sa.Column(
            "reasons",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eval_ms", sa.Integer),
    )
    op.create_index("policy_decisions_run", "policy_decisions", ["run_id"])


def downgrade() -> None:
    op.drop_table("policy_decisions")
    op.drop_table("detections")
    op.drop_table("blobs")
    op.drop_table("events")
    op.drop_table("runs")
    op.drop_table("projects")
