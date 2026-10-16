"""Give server-originated events their own ordering slot: events.sub_seq.

`seq` is assigned by the SDK in the agent's own process (EVENTS.md §1).
The control plane also writes events of its own (detection.raised,
policy.decision) and used to number them `max(persisted seq) + 1` -- but
the SDK may already have used that number for an event still in flight,
and the upsert on (run_id, seq) then silently overwrote one with the
other. Server events now keep the SDK's numbering untouched: each one
attaches to the agent event it follows (`seq`) and takes the next free
`sub_seq` (1, 2, ...) under it. SDK events are always `sub_seq = 0`, so
the two writers can no longer address the same row.

`idempotency_key` lets a retried server write recognize its own earlier
success instead of recording the same detection twice.

Mirrors trazo_server.store.models.events (hand-kept in sync, same
convention as 0001_baseline.py).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("sub_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.add_column("events", sa.Column("idempotency_key", sa.Text, nullable=True))

    op.drop_constraint("events_pkey", "events", type_="primary")
    op.create_primary_key("events_pkey", "events", ["run_id", "seq", "sub_seq"])

    op.drop_index("events_kind", table_name="events")
    op.create_index("events_kind", "events", ["run_id", "kind", "seq", "sub_seq"])

    # Race-free idempotency: a retried write either inserts or hits this.
    op.create_index(
        "events_idempotency",
        "events",
        ["run_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    # The live per-run stream re-reads a run's server events on every
    # poll (they can land behind its cursor); keep that off a full scan.
    op.create_index(
        "events_server",
        "events",
        ["run_id", "seq", "sub_seq"],
        postgresql_where=sa.text("sub_seq > 0"),
    )


def downgrade() -> None:
    # The old key is (run_id, seq), and server events now share their seq
    # with the SDK event they follow. Rather than drop them, move each to a
    # fresh seq above everything in its run -- where the old scheme would
    # have put it -- so every event survives the rollback. Run this with
    # the control plane stopped: an SDK event persisted mid-downgrade could
    # take one of those numbers.
    op.execute(
        """
        WITH ranked AS (
            SELECT e.run_id, e.seq, e.sub_seq,
                   (SELECT max(m.seq) FROM events m WHERE m.run_id = e.run_id)
                   + row_number() OVER (
                       PARTITION BY e.run_id ORDER BY e.seq, e.sub_seq
                   ) AS new_seq
            FROM events e
            WHERE e.sub_seq > 0
        )
        UPDATE events
        SET seq = ranked.new_seq, sub_seq = 0
        FROM ranked
        WHERE events.run_id = ranked.run_id
          AND events.seq = ranked.seq
          AND events.sub_seq = ranked.sub_seq
        """
    )
    op.drop_index("events_server", table_name="events")
    op.drop_index("events_idempotency", table_name="events")
    op.drop_index("events_kind", table_name="events")
    op.create_index("events_kind", "events", ["run_id", "kind", "seq"])
    op.drop_constraint("events_pkey", "events", type_="primary")
    op.create_primary_key("events_pkey", "events", ["run_id", "seq"])
    op.drop_column("events", "idempotency_key")
    op.drop_column("events", "sub_seq")
