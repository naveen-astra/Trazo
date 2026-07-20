"""Async SQLAlchemy engine factory.

Settings.database_url (config.py) is a plain ``postgresql://`` URL so it
reads naturally in docs and .env files; the control plane is asyncio-native
end to end, so we always force the asyncpg driver when actually connecting.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def async_database_url(database_url: str) -> str:
    """Return ``database_url`` with the drivername forced to postgresql+asyncpg."""
    return (
        make_url(database_url)
        .set(drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False)
    )


def create_engine(database_url: str) -> AsyncEngine:
    """Build the AsyncEngine the control plane uses for all Postgres access."""
    return create_async_engine(async_database_url(database_url))
