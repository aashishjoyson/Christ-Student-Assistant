import { useState } from "react";
import { sendFeedback } from "../api/client";
import type { FeedbackReason, ModelMode } from "../api/types";
import { ThumbDownIcon, ThumbUpIcon } from "./icons";

const REASONS: { code: FeedbackReason; label: string }[] = [
  { code: "wrong_answer", label: "Wrong answer" },
  { code: "not_helpful", label: "Not helpful" },
  { code: "missing_source", label: "No source" },
  { code: "too_slow", label: "Too slow" },
  { code: "other", label: "Other" },
];

type State = "idle" | "choosing" | "sending" | "sent" | "failed";

/** Thumbs under an answer. Sends only the answer id, the rating and a fixed reason code, so nothing anyone typed is stored. */
export function FeedbackBar({ messageId, modelMode }: { messageId: string; modelMode?: ModelMode | null }) {
  const [state, setState] = useState<State>("idle");

  async function submit(rating: "up" | "down", reason?: FeedbackReason) {
    setState("sending");
    try {
      await sendFeedback({ messageId, rating, reason, modelMode });
      setState("sent");
    } catch {
      setState("failed");
    }
  }

  if (state === "sent") return <div className="feedback done" role="status">Thanks, that helps us improve.</div>;
  return (
    <div className="feedback">
      <span className="muted">Was this helpful?</span>
      <button type="button" className="thumb" aria-label="This answer helped" disabled={state === "sending"} onClick={() => submit("up")}>
        <ThumbUpIcon />
      </button>
      <button type="button" className="thumb" aria-label="This answer did not help" aria-expanded={state === "choosing"}
        disabled={state === "sending"} onClick={() => setState("choosing")}>
        <ThumbDownIcon />
      </button>
      {state === "choosing" && (
        <span className="reasons" role="group" aria-label="What was wrong?">
          {REASONS.map((r) => (
            <button type="button" key={r.code} className="chip" onClick={() => submit("down", r.code)}>{r.label}</button>
          ))}
        </span>
      )}
      {state === "failed" && <span className="muted" role="alert">Could not send. Try again.</span>}
    </div>
  );
}
