"""The REST API application factory."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.responses import Response

from mandate import __version__
from mandate.api.approval_links import link_secrets
from mandate.api.audit import AuditMiddleware
from mandate.api.console import install_console
from mandate.api.errors import RequestContextMiddleware, install_error_handlers
from mandate.api.keys import build_keyring
from mandate.api.notify import HttpSender, Notifier
from mandate.api.routes import (
    approvals,
    audit,
    auth,
    authority,
    console,
    gateway,
    lineage,
    tenants,
    tokens,
    users,
    webhooks,
)
from mandate.api.security import RateLimiter, require_caller
from mandate.api.tenancy import FalkorTenantBackend, Runtimes, TenantBackend
from mandate.clock import Clock, SystemClock
from mandate.config import Settings, get_settings, token_secrets
from mandate.errors import MandateError
from mandate.graph.client import GraphClient
from mandate.logging import configure_logging
from mandate.observability import metrics

LOGIN_ATTEMPTS_PER_MINUTE = 10  # per email address


def create_app(
    settings: Settings | None = None,
    backend: TenantBackend | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    """Build the API. Fails at startup if the admin API key is missing or too short."""
    settings = settings or get_settings()
    api_key = settings.require_api_key()
    configure_logging(settings.mandate_log_level)

    if backend is None:
        backend = FalkorTenantBackend(GraphClient.from_settings(settings))

    interval = settings.mandate_notify_interval_seconds

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Run the notifier beside the API while it serves (when an interval is set)."""
        notifier: Notifier = app.state.notifier
        thread = None
        if interval > 0:
            thread = threading.Thread(
                target=notifier.run, args=(interval,), name="notifier", daemon=True
            )
            thread.start()
        try:
            yield
        finally:
            notifier.stop()
            if thread is not None:
                thread.join(timeout=interval + 6)

    app = FastAPI(title="Agent Mandate", version=__version__, lifespan=lifespan)
    app.state.api_key = api_key
    app.state.keyring = build_keyring(
        api_key, settings.mandate_api_keys.get_secret_value() if settings.mandate_api_keys else None
    )
    app.state.limiter = RateLimiter(settings.mandate_rate_limit_per_min)
    app.state.runtimes = Runtimes(backend, clock or SystemClock())
    app.state.results_dir = settings.mandate_results_dir
    app.state.token_secrets = token_secrets(settings)  # newest first: the first signs
    app.state.token_ttl_seconds = settings.mandate_token_ttl_seconds
    app.state.link_secrets = link_secrets(app.state.token_secrets)
    app.state.event_poll_seconds = 1.0  # how often an open console stream reads the graph
    app.state.event_max_seconds = 300.0  # then the stream ends and the browser reconnects
    app.state.session_ttl = settings.mandate_session_ttl_seconds
    app.state.session_idle_ms = settings.mandate_session_idle_seconds * 1000
    app.state.cookie_secure = settings.mandate_cookie_secure
    app.state.login_limiter = RateLimiter(LOGIN_ATTEMPTS_PER_MINUTE)
    app.state.webhook_allow_private = settings.mandate_webhook_allow_private
    app.state.notifier = Notifier(
        app.state.runtimes,
        link_secret=app.state.link_secrets[0],
        public_url=settings.mandate_public_url,
        link_ttl_seconds=settings.mandate_notify_link_ttl_seconds,
        sender=HttpSender(allow_private=settings.mandate_webhook_allow_private),
    )
    # Starlette runs the last-added middleware first: the request id exists before auditing.
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        up = backend.ping()
        status_code = 200 if up else 503
        body = {"status": "ok" if up else "degraded", "graph": "up" if up else "down"}
        return JSONResponse(body, status_code=status_code)

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        """Ready only if the graph answers a real read, not just a ping."""
        try:
            ready = backend.ping()
            if ready:
                backend.list()
        except MandateError:
            ready = False
        body = {"status": "ready" if ready else "not_ready", "version": __version__}
        return JSONResponse(body, status_code=200 if ready else 503)

    @app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_caller)])
    def prometheus_metrics() -> Response:
        """Prometheus text format; needs the API key like everything except health."""
        return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(audit.router)
    app.include_router(tenants.router)
    app.include_router(authority.router)
    app.include_router(gateway.router)
    app.include_router(lineage.router)
    app.include_router(lineage.tenant_router)
    app.include_router(console.tenant_router)
    app.include_router(console.router)
    app.include_router(tokens.router)
    app.include_router(approvals.tenant_router)
    app.include_router(approvals.router)  # no API key: the link is the credential
    app.include_router(webhooks.router)
    if settings.mandate_static_dir is not None:
        install_console(app, settings.mandate_static_dir)  # last: it catches what is left
    return app
