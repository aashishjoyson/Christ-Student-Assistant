"""Application settings, loaded once from environment variables and the repo-root .env file.

Every model/provider id lives here and only here. Blank values in .env are treated as "unset".
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
STORAGE_DIR = REPO_ROOT / "storage"

log = logging.getLogger(__name__)


def _secret(value: SecretStr | None) -> str:
    return value.get_secret_value() if value else ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # --- App ---
    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: SecretStr | None = None  # signs applicant session tokens
    app_timezone: str = "Asia/Kolkata"
    frontend_origin: str = "http://localhost:5173"

    # --- Models 1 & 2: hosted LLM (same provider + model for both) ---
    llm_provider: Literal["openai", "openrouter"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_chat_model: str = ""  # set in .env; verify the id on OpenAI's models page
    openai_embedding_model: str = "text-embedding-3-small"
    openrouter_api_key: SecretStr | None = None
    openrouter_chat_model: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 800
    llm_temperature: float | None = None  # not sent when unset (reasoning models reject it)
    llm_reasoning_effort: str | None = None  # not sent when unset
    history_turns: int = 6  # prior chat turns given to the LLM (same for every mode)

    # --- Model 3: remote OpenAI-compatible endpoint serving the LoRA adapter ---
    model3_base_url: str = ""
    model3_api_key: SecretStr | None = None
    model3_model: str = ""  # served name of the adapter, e.g. "cu-helpdesk-lora"
    model3_base_model_id: str = ""  # e.g. "Qwen/Qwen3-4B-Instruct-2507"
    model3_adapter_id: str = ""  # e.g. "your-hf-user/cu-helpdesk-lora@<revision>"
    model3_ablation_model: str = ""  # optional: served base model name (evaluation-only ablation)
    model3_temperature: float | None = 0.2
    model3_timeout_seconds: float = 90.0  # scale-to-zero endpoints have cold starts
    model3_max_retries: int = 1

    # --- RAG ---
    rag_top_k: int = 4
    rag_max_distance: float = 0.6
    rag_chunk_size: int = 900
    rag_chunk_overlap: int = 120
    rag_no_evidence_short_circuit: bool = True
    chroma_persist_dir: Path = STORAGE_DIR / "chroma"
    chroma_collection: str = "cu_helpdesk_docs"
    local_docs_dir: Path = REPO_ROOT / "data" / "sample_docs"

    # --- Google Drive ingestion ---
    google_drive_folder_id: str = ""
    google_drive_auth_mode: Literal["service_account", "oauth"] = "service_account"
    google_drive_credentials_file: Path | None = None
    google_drive_token_file: Path = REPO_ROOT / "secrets" / "drive-token.json"
    drive_poll_enabled: bool = False
    drive_sync_interval_seconds: int = 300

    # --- Relational store ---
    database_url: str = f"sqlite:///{(STORAGE_DIR / 'helpdesk.db').as_posix()}"

    # --- Applicant verification (prototype) ---
    applicant_session_ttl_minutes: int = 30
    verify_max_attempts: int = 5
    verify_window_minutes: int = 15

    # --- Email (simulated by default) ---
    email_provider: Literal["console", "smtp"] = "console"
    email_send_enabled: bool = False
    email_from: str = "helpdesk-demo@example.com"
    email_recipient_allowlist: str = ""  # comma-separated addresses or @domains; required for real sending
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_use_starttls: bool = True
    notification_cooldown_minutes: int = 15
    notification_max_per_day: int = 3
    outbox_dir: Path = STORAGE_DIR / "outbox"

    # --- LLMOps ---
    trace_dir: Path = STORAGE_DIR / "traces"
    trace_include_text: bool = False
    mlflow_tracking_uri: str = ""  # blank = MLflow disabled; e.g. sqlite:///storage/mlflow.db

    # --- Admin (local development only) ---
    admin_api_key: SecretStr | None = None

    @field_validator(
        "chroma_persist_dir", "local_docs_dir", "google_drive_credentials_file", "google_drive_token_file",
        "outbox_dir", "trace_dir", mode="after",
    )
    @classmethod
    def _repo_relative(cls, value: Path | None) -> Path | None:
        """Relative paths in .env are relative to the repo root, not to wherever uvicorn was started."""
        if value is None or value.is_absolute():
            return value
        return (REPO_ROOT / value).resolve()

    # ---------- derived helpers ----------
    @property
    def primary_api_key(self) -> str:
        return _secret(self.openai_api_key if self.llm_provider == "openai" else self.openrouter_api_key)

    @property
    def primary_chat_model(self) -> str:
        return self.openai_chat_model if self.llm_provider == "openai" else self.openrouter_chat_model

    @property
    def primary_configured(self) -> bool:
        return bool(self.primary_api_key and self.primary_chat_model)

    @property
    def model3_configured(self) -> bool:
        """Model 3 is usable only when the endpoint AND the adapter identity are declared."""
        return all([self.model3_base_url, self.model3_model, self.model3_base_model_id, self.model3_adapter_id])

    @property
    def allowlist(self) -> list[str]:
        return [e.strip() for e in self.email_recipient_allowlist.split(",") if e.strip()]

    @property
    def admin_enabled(self) -> bool:
        key = _secret(self.admin_api_key)
        return bool(key) and key != "change-this-for-local-development"

    def secret_key_bytes(self) -> bytes:
        key = _secret(self.app_secret_key)
        if key:
            return key.encode()
        if self.app_env == "production":
            raise RuntimeError("APP_SECRET_KEY must be set in production.")
        return _EPHEMERAL_SECRET


_EPHEMERAL_SECRET = secrets.token_bytes(32)  # dev fallback: tokens die on restart


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not _secret(settings.app_secret_key) and settings.app_env != "production":
        log.warning("APP_SECRET_KEY not set; using an ephemeral key (applicant sessions reset on restart).")
    return settings
