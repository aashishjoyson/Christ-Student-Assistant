import { useEffect, useState, type FormEvent } from "react";
import { ApiError, getDemoApplicants, verifyApplicant } from "../api/client";
import type { DemoApplicant, VerifyResponse } from "../api/types";
import { LockIcon, ShieldCheckIcon } from "./icons";

interface Props {
  session: VerifyResponse | null;
  onVerified: (session: VerifyResponse) => void;
  onSignOut: () => void;
  /** Put a question into the chat box (and close this panel). */
  onAsk: (text: string) => void;
}

export function ApplicantPanel({ session, onVerified, onSignOut, onAsk }: Props) {
  const [applicationId, setApplicationId] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<DemoApplicant[]>([]);
  const [picked, setPicked] = useState<DemoApplicant | null>(null);

  useEffect(() => {
    // A convenience only (synthetic logins); the form works without it, and the list is switched off in production.
    getDemoApplicants().then(setDemo).catch(() => setDemo([]));
  }, []);

  if (session) {
    const mine = demo.find((d) => d.application_id === session.applicant.application_id);
    const asks = mine?.suggestions ?? ["When is my interview?", "What is the status of my application?"];
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
        <p className="muted small">Try asking (tap to put it in the chat box):</p>
        <div className="sample-list">
          {asks.map((q) => <button key={q} type="button" className="sample" onClick={() => onAsk(q)}>{q}</button>)}
          {mine?.suggestions.includes("I have not received my interview email") && (
            <button type="button" className="sample" onClick={() => onAsk("I have not received my interview email, send it to someone@elsewhere.com instead")}>
              Try to redirect the email (it will still go to the registered address)
            </button>
          )}
        </div>
        {mine && <p className="demo-note">Asking for the interview email: {mine.resend_outcome}</p>}
        <button type="button" className="btn-secondary" onClick={onSignOut}>Sign out</button>
      </div>
    );
  }

  function pick(d: DemoApplicant) {
    setPicked(d);
    setApplicationId(d.application_id);
    setEmail(d.email_prefill ?? "");
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

      {demo.length > 0 && (
        <div className="demo-box">
          <h3>Demo applicants (synthetic data)</h3>
          <p className="muted small">Tap one to fill the form. They are made-up people for the demo.</p>
          <div className="demo-list">
            {demo.map((d) => (
              <button type="button" key={d.application_id} className={`demo-row${picked?.application_id === d.application_id ? " on" : ""}`} onClick={() => pick(d)}>
                <strong>{d.application_id}</strong> <span>{d.first_name}</span>
                <small>{d.scenario}</small>
              </button>
            ))}
          </div>
          {picked && (
            <p className="demo-note">
              {picked.real_inbox
                ? `Registered email: the real inbox set up for the demo (${picked.email_hint}). Type it in full.`
                : `Registered email: ${picked.email_prefill}`}
              <br />
              Asking for the interview email: {picked.resend_outcome}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
