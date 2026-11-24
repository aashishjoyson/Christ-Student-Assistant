import type { Health, ModelMode } from "../api/types";
import { MODE_LABELS } from "../api/types";

const DESCRIPTIONS: Record<ModelMode, string> = {
  direct: "Hosted LLM only. Not grounded in university documents.",
  rag: "Same hosted LLM + retrieved university documents, with citations.",
  rag_peft: "Same retrieval + an open model fine-tuned with LoRA, served from a cloud endpoint.",
};

// Compact two-line labels for the narrow widget; the full label stays as the accessible name.
const SHORT: Record<ModelMode, { title: string; sub: string }> = {
  direct: { title: "Model 1", sub: "Direct LLM" },
  rag: { title: "Model 2", sub: "LLM + RAG" },
  rag_peft: { title: "Model 3", sub: "RAG + PEFT" },
};

interface Props {
  value: ModelMode;
  onChange: (mode: ModelMode) => void;
  health: Health | null;
}

export function ModelSelector({ value, onChange, health }: Props) {
  return (
    <div className="model-selector">
      <div className="segmented" role="radiogroup" aria-label="Model configuration">
        {(Object.keys(MODE_LABELS) as ModelMode[]).map((mode) => {
          const status = health?.models[mode];
          const notConfigured = status !== undefined && !status.configured;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={value === mode}
              aria-label={`${MODE_LABELS[mode]}${notConfigured ? " (not configured)" : ""}`}
              className={`model-option${value === mode ? " selected" : ""}`}
              onClick={() => onChange(mode)}
              title={DESCRIPTIONS[mode]}
            >
              <span className="model-title">
                {status && <span className={`status-dot${notConfigured ? " off" : ""}`} aria-hidden="true" />}
                {SHORT[mode].title}
              </span>
              <span className="model-sub">{notConfigured ? "Not configured" : SHORT[mode].sub}</span>
            </button>
          );
        })}
      </div>
      <p className="model-description">{DESCRIPTIONS[value]}</p>
    </div>
  );
}
