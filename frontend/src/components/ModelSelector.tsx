import type { Health, ModelMode } from "../api/types";
import { MODE_LABELS } from "../api/types";

const DESCRIPTIONS: Record<ModelMode, string> = {
  direct: "Hosted LLM only. Not grounded in university documents.",
  rag: "Same hosted LLM + retrieved university documents, with citations.",
  rag_peft: "Same retrieval + an open model fine-tuned with LoRA, served from a cloud endpoint.",
};

interface Props {
  value: ModelMode;
  onChange: (mode: ModelMode) => void;
  health: Health | null;
}

export function ModelSelector({ value, onChange, health }: Props) {
  return (
    <div className="model-selector" role="radiogroup" aria-label="Model configuration">
      {(Object.keys(MODE_LABELS) as ModelMode[]).map((mode) => {
        const status = health?.models[mode];
        const notConfigured = status !== undefined && !status.configured;
        return (
          <button
            key={mode}
            role="radio"
            aria-checked={value === mode}
            className={`model-option${value === mode ? " selected" : ""}`}
            onClick={() => onChange(mode)}
            title={DESCRIPTIONS[mode]}
          >
            <span className="model-label">{MODE_LABELS[mode]}</span>
            {notConfigured && <span className="badge warn">Not configured</span>}
            {status?.configured && status.model && <span className="model-id">{status.model}</span>}
          </button>
        );
      })}
      <p className="model-description">{DESCRIPTIONS[value]}</p>
    </div>
  );
}
