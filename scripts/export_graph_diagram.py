"""Write the compiled LangGraph as Mermaid to docs/graph.mmd (useful for the report and viva).

Usage (from repo root, backend venv active):
    python scripts/export_graph_diagram.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.graph.builder import build_graph  # noqa: E402
from app.graph.deps import GraphDeps  # noqa: E402
from app.rag.base import NullRetriever  # noqa: E402


def main() -> None:
    deps = GraphDeps(
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        session_factory=MagicMock(),
        primary_llm=None,
        model3_llm=None,
        retriever=NullRetriever(),
        email_provider=MagicMock(),
    )
    mermaid = build_graph(deps).get_graph().draw_mermaid()
    out = REPO_ROOT / "docs" / "graph.mmd"
    out.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
