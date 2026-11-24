"""The container files cannot be built here (no Docker engine was running), so these tests guard what matters most about them: no secret or
private document can end up in an image, the API is not published, and the chat stream is not buffered."""

from __future__ import annotations

from app.core.config import REPO_ROOT


def read(*parts: str) -> str:
    return REPO_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_nothing_private_can_enter_an_image() -> None:
    ignore = read(".dockerignore").splitlines()
    for pattern in (".env", ".env.*", "secrets/", "storage/", "data/private/", "data/sample_docs/", "data/peft/*.jsonl", "adapters/", "*.db"):
        assert pattern in ignore, pattern
    api = read("backend", "Dockerfile")
    for forbidden in ("COPY .env", "COPY secrets", "COPY storage", "COPY data/sample_docs", "ADD .env", "ENV OPENAI", "ARG OPENAI"):
        assert forbidden not in api, forbidden


def test_the_api_runs_as_a_normal_user_and_trusts_the_proxy_header_for_rate_limits() -> None:
    api = read("backend", "Dockerfile")
    assert "USER helpdesk" in api and "HEALTHCHECK" in api
    assert "--proxy-headers" in api and "-c backend/requirements.lock" in api


def test_compose_keeps_the_api_private_and_the_key_file_read_only() -> None:
    compose = read("docker-compose.yml")
    assert "env_file: .env" in compose and "./secrets:/srv/helpdesk/secrets:ro" in compose
    assert 'expose:\n      - "8000"' in compose and '"8000:8000"' not in compose  # only the web container reaches the API
    assert "OPENAI_API_KEY" not in compose and "ADMIN_API_KEY" not in compose  # no secret value, or even its name, is written into the file
    assert "service_healthy" in compose


def test_nginx_does_not_buffer_the_stream_and_proxies_only_the_api() -> None:
    conf = read("frontend", "nginx.conf")
    assert "proxy_buffering off" in conf and "proxy_pass http://api:8000" in conf and "proxy_read_timeout" in conf
    assert "try_files $uri /index.html" in conf and "X-Content-Type-Options" in conf
