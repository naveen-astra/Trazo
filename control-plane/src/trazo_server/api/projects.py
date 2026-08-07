"""Resolving the ``?project=`` filter every read surface accepts.

The event envelope carries a project *name* ("research-assistant"), and
that is what a caller has: it is the string the SDK was configured with.
The store keys runs on a hash of it (store_worker._derive_project_id) so
replicas agree on an id without a lookup-then-create race. Nothing ever
bridged the two, so `?project=my-agent` matched no rows and returned an
empty page — indistinguishable from a project that genuinely has no runs.

Lives in its own module because every surface taking ``?project=``
(runs, stats, the live firehose) must resolve it the same way. The first
fix only covered the query endpoints and left the firehose filtering on
the raw name, which still delivered nothing — hence one shared helper
rather than a rule to remember.
"""

from __future__ import annotations

from trazo_server.store.trace_store import TraceStore

_PROJECT_ID_PREFIX = "proj_"


async def resolve_project_id(store: TraceStore, project: str | None) -> str | None:
    """Map a ``?project=`` value to a stored ``project_id``.

    Accepts either form: an id is passed through untouched, anything else
    is looked up by name. An unknown value is returned unchanged so it
    matches nothing, rather than being silently widened to "all
    projects" — a filter that quietly stops filtering is worse than one
    that returns an empty page.
    """
    if project is None or project.startswith(_PROJECT_ID_PREFIX):
        return project
    names = await store.list_project_names()
    for project_id, name in names.items():
        if name == project:
            return project_id
    return project
