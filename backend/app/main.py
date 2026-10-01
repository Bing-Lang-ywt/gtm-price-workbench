import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

from app.core.config import ENABLE_SCHEDULER
from app.core.db import init_db, get_session
from sqlmodel import Session
from app.routes import (
    alerts,
    alert_rules,
    catalog,
    channels,
    comparison,
    crawl,
    dashboard,
    discovery,
    export,
    model_mappings,
    prices,
    skus,
    feedback,
    auth,
    params,
    diag,
    energy_labels,
    energy_label_pack,
)
from app.services.crawl import shutdown_scheduler, start_scheduler
from app.core.logging_setup import configure_logging

configure_logging()

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if ENABLE_SCHEDULER:
        start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="Nord-East Europe Phone Price Monitor API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "data": None, "message": exc.detail},
    )


app.include_router(auth.router, prefix="/api/v1")
app.include_router(channels.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(model_mappings.router, prefix="/api/v1")
app.include_router(skus.router, prefix="/api/v1")
app.include_router(prices.router, prefix="/api/v1")
app.include_router(comparison.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(alert_rules.router, prefix="/api/v1")
app.include_router(crawl.router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(discovery.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(params.router, prefix="/api/v1")
app.include_router(diag.router, prefix="/api/v1")
app.include_router(energy_labels.router, prefix="/api/v1")
app.include_router(energy_label_pack.router, prefix="/api/v1")


@app.get("/health")
def health():
    # Surface the headless-browser pool so an open circuit breaker is visible
    # without tailing logs (operator PDP channels depend on it).
    from app.crawling.browser_pool import browser_status

    return {
        "code": 0,
        "data": {"status": "ok", "browser": browser_status()},
        "message": "",
    }


# Clean, un-prefixed URL for the public EPREL energy-label grid (proxied by
# Caddy /energy-labels* -> backend). Reuses the auth-free view from the
# energy-labels router.
@app.get("/energy-labels", response_class=HTMLResponse)
@app.get("/energy-labels/view", response_class=HTMLResponse)
def energy_labels_view_root(
    supplier: str = Query(None),
    device_type: str = Query(None),
    energy_class: str = Query(None),
    q: str = Query(None),
    session: Session = Depends(get_session),
):
    from app.routes import energy_labels as _el

    return _el.energy_labels_view(supplier, device_type, energy_class, q, session)


# Clean, un-prefixed URL for the combined energy-label pack download page
# (proxied by Caddy /energy-label-pack* -> backend).
@app.get("/energy-label-pack", response_class=HTMLResponse)
def energy_label_pack_root():
    from app.routes import energy_label_pack as _elp

    return _elp.pack_page()
