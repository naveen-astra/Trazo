"""Deriving a stable ``project_id`` from a logical project name.

A leaf module (like ``ulid.py`` and ``topics.py``) because both the
ingest/worker path and the synchronous policy path need the same answer,
and neither should have to import the other to get it.
"""

from __future__ import annotations

import hashlib


def derive_project_id(project_name: str) -> str:
    """Stable project_id from the logical project name.

    The event envelope carries ``project`` (a name like
    "research-assistant"), never a ULID (EVENTS.md §1) — hashing the name
    gives every worker/replica the same id for the same name without a
    lookup-then-create round trip or a race on first sight of a project.
    """
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:20]
    return f"proj_{digest}"
