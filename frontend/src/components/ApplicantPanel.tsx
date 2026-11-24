import { useState, type FormEvent } from "react";
import { ApiError, verifyApplicant } from "../api/client";
import type { VerifyResponse } from "../api/types";
import { LockIcon, ShieldCheckIcon } from "./icons";

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
      <div className="verify">
        <div className="verify-head">
          <span className="verify-icon ok"><ShieldCheckIcon /></span>
          <h2>Verified applicant</h2>
        </div>
        <p className="who">
          <strong>{session.applicant.first_name}</strong> <span className="badge good">Verified</span>
          <br />
          {session.applicant.application_id}
          <br />
          <span className="muted">{session.applicant.masked_email}</span>
        </p>
        <p className="muted small">Ask about your application status, interview, or a missing interview email.</p>
        <button type="button" className="btn-secondary" onClick={onSignOut}>Sign out</button>
      </div>
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
    <div className="verify">
      <div className="verify-head">
        <span className="verify-icon"><LockIcon /></span>
        <h2>Verify applicant</h2>
      </div>
      <form onSubmit={submit}>
        <label>
          Application ID
          <input value={applicationId} onChange={(e) => setApplicationId(e.target.value)} placeholder="CUAPP-DEMO-0001" required />
        </label>
        <label>
          Registered email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Checking..." : "Verify"}</button>
        {error && <p className="error-text" role="alert">{error}</p>}
      </form>
      <p className="muted small">Prototype check only (application ID + email). A real service would use university SSO.</p>
    </div>
  );
}
