import { useState, type FormEvent } from "react";

import { ApiError, signIn } from "../api/runApi";

function describeFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "Incorrect password.";
    if (error.status === 429) {
      const minutes = error.retryAfterSeconds ? Math.ceil(error.retryAfterSeconds / 60) : null;
      return minutes
        ? `Too many failed attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`
        : "Too many failed attempts. Try again later.";
    }
    return error.message;
  }
  return "Could not reach the control plane. Check your connection and try again.";
}

export default function LoginPage({ onSignedIn }: { onSignedIn: () => Promise<void> }) {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!password || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await signIn(password);
      await onSignedIn();
    } catch (failure) {
      setError(describeFailure(failure));
      setPassword("");
      setSubmitting(false);
    }
  }

  return (
    <main className="login">
      <form className="login__card" onSubmit={handleSubmit} noValidate>
        <div className="login__brand">
          <div className="sidebar__mark" />
          <span className="sidebar__name">Trazo</span>
        </div>
        <h1 className="login__title">Sign in</h1>
        <p className="login__subtitle">
          Enter the dashboard password for this deployment to view its runs.
        </p>

        <label className="field">
          <span className="field__label">Password</span>
          <input
            className="login__input"
            type="password"
            name="password"
            autoComplete="current-password"
            autoFocus
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={error !== null}
            aria-describedby={error ? "login-error" : undefined}
          />
        </label>

        {error && (
          <p id="login-error" className="login__error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="replay-btn replay-btn--primary login__submit"
          disabled={!password || submitting}
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
