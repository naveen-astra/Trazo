import { useState } from "react";

import { blobUrl, isBlobRef, type EventOut } from "../api/runApi";
import { formatPosition } from "../lib/eventOrder";

interface BlobFieldProps {
  field: string;
  sha256: string;
}

export function BlobField({ field, sha256 }: BlobFieldProps) {
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

// A single retrieved document, as MemoryInspector renders it -- results
// is typed `Any` server-side (EVENTS.md §2.3's memory.read), and this
// demo corpus's own shape is a plain list[str] (no per-doc score), so
// both a bare string and a {document, score} object are handled.
interface RetrievedDoc {
  document: string;
  score: number | null;
}

function normalizeRetrievedDocs(results: unknown): RetrievedDoc[] | null {
  if (!Array.isArray(results)) {
    return null;
  }
  return results.map((entry) => {
    if (typeof entry === "string") {
      return { document: entry, score: null };
    }
    if (typeof entry === "object" && entry !== null) {
      const record = entry as Record<string, unknown>;
      const document = record.document ?? record.text ?? record.content;
      const score = record.score ?? record.distance;
      return {
        document: typeof document === "string" ? document : JSON.stringify(entry),
        score: typeof score === "number" ? score : null,
      };
    }
    return { document: String(entry), score: null };
  });
}

interface MemoryInspectorProps {
  event: EventOut;
}

/** TRZ-P6-06: a structured view of one memory.read boundary -- query, k,
 * and every retrieved document (with its score, when the store reports
 * one) -- instead of making a reader parse the raw JSON payload below. */
function MemoryInspector({ event }: MemoryInspectorProps) {
  const payload = event.payload as Record<string, unknown>;
  const query = payload.query;
  const k = payload.k;
  const docs = isBlobRef(payload.results) ? null : normalizeRetrievedDocs(payload.results);

  return (
    <section className="memory-inspector">
      <p className="memory-inspector__query">
        <strong>query:</strong> {typeof query === "string" ? query : JSON.stringify(query)}
        {typeof k === "number" ? ` · k=${k}` : ""}
      </p>
      {docs === null ? (
        <p style={{ color: "var(--text-muted)" }}>
          results offloaded — fetch the blob below to inspect them.
        </p>
      ) : docs.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>no documents retrieved</p>
      ) : (
        <ol className="memory-inspector__docs">
          {docs.map((doc, index) => (
            <li key={index}>
              <span className="memory-inspector__doc-text">{doc.document}</span>
              {doc.score !== null && (
                <span className="memory-inspector__doc-score">score {doc.score.toFixed(3)}</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

interface PayloadDrawerProps {
  event: EventOut;
  onClose: () => void;
}

/** Full event payload, with a fetch button for any offloaded (>32KB,
 * EVENTS.md §1) field instead of the raw `{"$blob": sha256}` placeholder.
 * memory.read additionally gets a structured MemoryInspector view above
 * the raw payload (TRZ-P6-06). */
export default function PayloadDrawer({ event, onClose }: PayloadDrawerProps) {
  const blobFields = Object.entries(event.payload).filter(([, value]) => isBlobRef(value));

  return (
    <div className="payload-drawer" role="dialog" aria-label={`payload for ${event.kind}`}>
      <button type="button" className="payload-drawer__close" onClick={onClose} aria-label="close">
        &times;
      </button>
      <h2>{event.kind}</h2>
      <p style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
        seq {formatPosition(event)} &middot; {event.ts}
      </p>
      {event.kind === "memory.read" && <MemoryInspector event={event} />}
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
