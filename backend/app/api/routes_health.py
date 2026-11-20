from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_container
from app.container import AppContainer
from app.domain.model_modes import MODE_LABELS, ModelMode
from app.schemas.health import HealthResponse, ModelStatus

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(container: AppContainer = Depends(get_container)) -> HealthResponse:
    s = container.settings
    primary = container.deps.primary_llm
    model3 = container.deps.model3_llm
    primary_info = {
        "configured": primary is not None,
        "provider": primary.provider if primary else s.llm_provider,
        "model": primary.model if primary else (s.primary_chat_model or None),
    }
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=s.app_env,
        models={
            ModelMode.DIRECT.value: ModelStatus(label=MODE_LABELS[ModelMode.DIRECT], retrieval=False, **primary_info),
            ModelMode.RAG.value: ModelStatus(label=MODE_LABELS[ModelMode.RAG], retrieval=True, **primary_info),
            ModelMode.RAG_PEFT.value: ModelStatus(
                label=MODE_LABELS[ModelMode.RAG_PEFT],
                configured=model3 is not None,
                provider=model3.provider if model3 else None,
                model=model3.model if model3 else None,
                base_model_id=s.model3_base_model_id or None,
                adapter_id=s.model3_adapter_id or None,
                retrieval=True,
            ),
        },
        retriever=container.deps.retriever.describe(),
        email={"provider": container.deps.email_provider.name, "send_enabled": s.email_send_enabled},
        drive={"configured": bool(s.google_drive_folder_id), "poll_enabled": s.drive_poll_enabled},
    )
