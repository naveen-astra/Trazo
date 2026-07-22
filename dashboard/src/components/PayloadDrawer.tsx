import { useState } from "react";

import { blobUrl, isBlobRef, type EventOut } from "../api/runApi";

interface BlobFieldProps {
  field: string;
  sha256: string;
}

function BlobField({ field, sha256 }: BlobFieldProps) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchBlob = () => {
    setLoading(true);
    setError(null);
    fetch(blobUrl(sha256))
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.text();
      })
      .then(setContent)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  };

  return (
    <div className="blob-field">
      <strong>{field}</strong> is offloaded ({sha256.slice(0, 18)}
      &hellip;)
      {content === null ? (
        <button type="button" className="blob-field__fetch" onClick={fetchBlob} disabled={loading}>
          {loading ? "fetching…" : "fetch blob"}
        </button>
      ) : (
        <pre>{content}</pre>
      )}
      {error && <p style={{ color: "var(--status-critical)" }}>{error}</p>}
    </div>
  );
}

interface PayloadDrawerProps {
  event: EventOut;
  onClose: () => void;
}

/** Full event payload, with a fetch button for any offloaded (>32KB,
 * EVENTS.md §1) field instead of the raw `{"$blob": sha256}` placeholder. */
export default function PayloadDrawer({ event, onClose }: PayloadDrawerProps) {
  const blobFields = Object.entries(event.payload).filter(([, value]) => isBlobRef(value));

  return (
    <div className="payload-drawer" role="dialog" aria-label={`payload for ${event.kind}`}>
      <button type="button" className="payload-drawer__close" onClick={onClose} aria-label="close">
        &times;
      </button>
      <h2>{event.kind}</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
        seq {event.seq} &middot; {event.ts}
      </p>
      {blobFields.length > 0 && (
        <section>
          {blobFields.map(([field, value]) => (
            <BlobField key={field} field={field} sha256={(value as { $blob: string }).$blob} />
          ))}
        </section>
      )}
      <pre>{JSON.stringify(event.payload, null, 2)}</pre>
    </div>
  );
}
