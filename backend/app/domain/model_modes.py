"""The three model configurations compared in this project."""

from __future__ import annotations

from enum import StrEnum


class ModelMode(StrEnum):
    DIRECT = "direct"  # Model 1 - hosted LLM, no retrieval
    RAG = "rag"  # Model 2 - same hosted LLM + retrieval
    RAG_PEFT = "rag_peft"  # Model 3 - same retrieval + LoRA-adapted open model


MODE_LABELS: dict[ModelMode, str] = {
    ModelMode.DIRECT: "Model 1 - Direct LLM",
    ModelMode.RAG: "Model 2 - LLM + RAG",
    ModelMode.RAG_PEFT: "Model 3 - LLM + RAG + PEFT",
}

# Prompt versions are recorded in every trace. Models 2 and 3 deliberately share
# the same RAG prompt so the only difference between them is the model.
PROMPT_VERSIONS: dict[ModelMode, str] = {
    ModelMode.DIRECT: "direct-v1",
    ModelMode.RAG: "rag-v2",  # v2: retrieved text can no longer forge the context delimiters
    ModelMode.RAG_PEFT: "rag-v2",
}
