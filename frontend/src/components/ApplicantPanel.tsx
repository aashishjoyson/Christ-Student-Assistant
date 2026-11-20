import { useState, type FormEvent } from "react";
import { ApiError, verifyApplicant } from "../api/client";
import type { VerifyResponse } from "../api/types";

interface Props {
  session: VerifyResponse | null;
  onVerified: (session: VerifyResponse) => void;
  onSignOut: () => void;
}

export function ApplicantPanel({ session, onVerified, onSignOut }: Props) {
  const [applicationId, setApplicationId] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (session) {
    return (
      <aside className="panel">
        <h2>Verified applicant</h2>
        <p>
          {session.applicant.first_name} &middot; {session.applicant.application_id}
          <br />
          <span className="muted">{session.applicant.masked_email}</span>
        </p>
        <p className="muted small">Ask about your application status, interview, or a missing interview email.</p>
        <button className="secondary" onClick={onSignOut}>Sign out</button>
      </aside>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onVerified(await verifyApplicant(applicationId.trim(), email.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verification failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="panel">
      <h2>Verify applicant</h2>
      <form onSubmit={submit}>
        <label>
          Application ID
          <input value={applicationId} onChange={(e) => setApplicationId(e.target.value)} placeholder="CUAPP-DEMO-0001" required />
        </label>
        <label>
          Registered email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <button type="submit" disabled={busy}>{busy ? "Checking..." : "Verify"}</button>
        {error && <p className="error-text">{error}</p>}
      </form>
      <p className="muted small">Prototype check only (application ID + email). A real service would use university SSO.</p>
    </aside>
  );
}
