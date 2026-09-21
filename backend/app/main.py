import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.migrations import add_missing_columns
from app.db.session import SessionLocal, engine
from app.models import *  # noqa: F403
from app.services.metrics import recalculate_all_daily_metrics
from app.services.user_accounts import ensure_agent_accounts, normalize_existing_accounts

configure_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

Base.metadata.create_all(bind=engine)
add_missing_columns(engine)

# One-time account normalization at startup:
# - promote legacy admin users to super admin
# - normalize emails to prenom.nom@microcred.com.tn
# - ensure portfolio manager accounts for imported agents exist
with SessionLocal() as startup_db:
    #normalize_existing_accounts(startup_db)
    ensure_agent_accounts(startup_db)
    startup_db.commit()

# TEMPORAIRE : recalcule toutes les métriques journalières déjà en base
# avec la nouvelle logique PAR120 (>120 au lieu de 120<days_overdue<365).
# A retirer une fois le recalcul effectué en production.
#with SessionLocal() as recalc_db:
    #updated = recalculate_all_daily_metrics(recalc_db)
    #recalc_db.commit()
    #logger.info("Recalcul PAR120 au demarrage : %s lignes de metriques regenerees", updated)

app = FastAPI(
    title=settings.app_name,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "frame-ancestors 'none'; "
        "img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "font-src 'self' data:;"
    )
    return response


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    print("\n" + "=" * 80)
    print("INTEGRITY ERROR")
    traceback.print_exc()

    if hasattr(exc, "orig"):
        print("ORIGINAL DATABASE ERROR:")
        print(exc.orig)

    print("=" * 80 + "\n")

    logger.exception("Database integrity error on %s", request.url.path)

    return JSONResponse(
        status_code=409,
        content={
            "detail": {
                "code": "integrity_error",
                "message": str(exc.orig) if hasattr(exc, "orig") else str(exc),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "server_error", "message": "Internal server error"}},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api_router, prefix=settings.api_v1_prefix)