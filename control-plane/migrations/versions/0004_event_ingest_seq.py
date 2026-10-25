"""Order the live firehose by when events were stored: events.ingest_seq.

The firehose used to page on event_id. Event ids are ULIDs carrying the
clock of whichever machine minted them -- the agent's for SDK events, the
control plane's for detections and policy decisions -- so when the two
clocks disagree, an event can be stored *after* one with a later id and
fall behind every subscriber's cursor, never to be delivered. The most
visible casualty was the critical-incident notification. ingest_seq is
assigned by Postgres on insert, independent of any clock.

Mirrors trazo_server.store.models.events (hand-kept in sync, same
convention as 0001_baseline.py).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are numbered as the column is added (in physical
    # order); only their relative order to *new* events matters, and every
    # new event numbers above them.
    op.add_column(
        "events",
        sa.Column(
            "ingest_seq",
            sa.BigInteger,
            sa.Identity(always=False),
            nullable=False,
        ),
    )
    op.create_index("events_ingest_seq", "events", ["ingest_seq"], unique=True)


def downgrade() -> None:
    op.drop_index("events_ingest_seq", table_name="events")
    op.drop_column("events", "ingest_seq")
