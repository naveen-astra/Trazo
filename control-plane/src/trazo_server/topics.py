"""Bus stream and consumer-group names — the single source of truth so the
ingest API (publisher, TRZ-P1-05) and the store worker (consumer,
TRZ-P1-06) never drift apart on naming (ARCHITECTURE.md §7 names the DLQ
stream as ``trazo:events:dlq``, i.e. ``EVENTS_STREAM + ":dlq"``).
"""

EVENTS_STREAM = "trazo:events"
STORE_WORKER_GROUP = "store-worker"
DETECTOR_WORKER_GROUP = "detector-worker"
