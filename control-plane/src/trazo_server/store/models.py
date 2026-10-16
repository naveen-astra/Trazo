"""SQLAlchemy Core table definitions mirroring DATABASE.md exactly.

Core, not ORM: the schema is simple and every query pattern lives
explicitly in TraceStore; an ORM's identity map and relationship loading
buy nothing here (CODING_STANDARDS.md §4 — boring technology, deliberately).
This module is the single source of truth Alembic's baseline migration
(migrations/versions/0001_baseline.py) was hand-derived from; the two must
stay in sync by inspection since generation isn't automated yet.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

projects = sa.Table(
    "projects",
    metadata,
    sa.Column("project_id", sa.Text, primary_key=True),
    sa.Column("name", sa.Text, nullable=False, unique=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

runs = sa.Table(
    "runs",
    metadata,
    sa.Column("run_id", sa.Text, primary_key=True),
    sa.Column(
        "project_id", sa.Text, sa.ForeignKey("projects.project_id"), nullable=False
    ),
    sa.Column("framework", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="running"),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("totals", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Index("runs_project_started", "project_id", sa.text("started_at DESC")),
    sa.Index("runs_status", "status", postgresql_where=sa.text("status = 'running'")),
)

events = sa.Table(
    "events",
    metadata,
    sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), nullable=False),
    sa.Column("seq", sa.BigInteger, nullable=False),
    sa.Column("event_id", sa.Text, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    sa.Column("step_id", sa.Text),
    sa.Column("agent_id", sa.Text),
    sa.Column("fingerprint", sa.Text),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("blobs", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    # 0 for every SDK event; 1, 2, ... for server events attached after the
    # SDK event at `seq` (migration 0003 explains why).
    sa.Column("sub_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.Column("idempotency_key", sa.Text, nullable=True),
    sa.PrimaryKeyConstraint("run_id", "seq", "sub_seq"),
    sa.Index("events_kind", "run_id", "kind", "seq", "sub_seq"),
    sa.Index(
        "events_idempotency",
        "run_id",
        "idempotency_key",
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    ),
    sa.Index(
        "events_server",
        "run_id",
        "seq",
        "sub_seq",
        postgresql_where=sa.text("sub_seq > 0"),
    ),
    sa.Index(
        "events_fingerprint",
        "fingerprint",
        postgresql_where=sa.text("fingerprint IS NOT NULL"),
    ),
    sa.Index(
        "events_payload_gin",
        "payload",
        postgresql_using="gin",
        postgresql_ops={"payload": "jsonb_path_ops"},
    ),
)

blobs = sa.Table(
    "blobs",
    metadata,
    sa.Column("sha256", sa.Text, primary_key=True),
    sa.Column("bytes", sa.BigInteger, nullable=False),
    sa.Column(
        "content_type", sa.Text, nullable=False, server_default="application/json"
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

detections = sa.Table(
    "detections",
    metadata,
    sa.Column("detection_id", sa.Text, primary_key=True),
    sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), nullable=False),
    sa.Column("detector", sa.Text, nullable=False),
    sa.Column("severity", sa.Text, nullable=False),
    sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("evidence", JSONB, nullable=False),
    sa.Column("details", JSONB, nullable=False),
    sa.Index("detections_run", "run_id"),
)

policy_decisions = sa.Table(
    "policy_decisions",
    metadata,
    sa.Column("decision_id", sa.Text, primary_key=True),
    sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), nullable=False),
    sa.Column("policy_id", sa.Text, nullable=False),
    sa.Column("action_kind", sa.Text, nullable=False),
    sa.Column("action_fp", sa.Text, nullable=False),
    sa.Column("decision", sa.Text, nullable=False),
    sa.Column("mode", sa.Text, nullable=False),
    sa.Column("reasons", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("eval_ms", sa.Integer),
    sa.Index("policy_decisions_run", "run_id"),
)

replay_reports = sa.Table(
    "replay_reports",
    metadata,
    # One row per run, upserted: only the latest `trazo verify` result
    # against the current code is meaningful, so a re-verify replaces
    # rather than accumulates (see ReplayReportRow's docstring).
    sa.Column("run_id", sa.Text, sa.ForeignKey("runs.run_id"), primary_key=True),
    sa.Column("boundary_fidelity", sa.Float, nullable=False),
    sa.Column("state_fidelity", sa.Float, nullable=False),
    sa.Column("matched", sa.Integer, nullable=False),
    sa.Column("reordered", sa.Integer, nullable=False),
    sa.Column(
        "divergences", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
    ),
    sa.Column("replay_overhead", sa.Float),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
)
