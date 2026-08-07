import { useEffect, useState } from "react";

import { IconCheck, IconCopy } from "./Icons";

/** Copy-to-clipboard with a two-second confirmation. Falls back to
 * selecting nothing and reporting failure rather than pretending it
 * worked — `navigator.clipboard` is unavailable on insecure origins,
 * which is exactly where a self-hosted dashboard often runs. */
export default function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(timer);
  }, [state]);

  return (
    <button
      type="button"
      className="copy-btn"
      title={state === "failed" ? "Clipboard unavailable on this origin" : label}
      aria-label={label}
      onClick={() => {
        navigator.clipboard
          ?.writeText(value)
          .then(() => setState("done"))
          .catch(() => setState("failed"));
        if (!navigator.clipboard) setState("failed");
      }}
    >
      {state === "done" ? <IconCheck /> : <IconCopy />}
      {state === "failed" && <span style={{ fontSize: 11 }}>unavailable</span>}
    </button>
  );
}
