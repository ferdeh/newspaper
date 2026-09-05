import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from pythonjsonlogger.json import JsonFormatter
from sqlalchemy import text

from app.api.notifications import router as notifications_router
from app.api.routes import router
from app.api.tbbm import router as tbbm_router
from app.api.tiktok_discovery import router as tiktok_discovery_router
from app.config import settings
from app.database import SessionLocal

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
logger = logging.getLogger("fuel-intelligence-api")

app = FastAPI(
    title="Fuel Distribution News & HSSE Intelligence API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    default_response_class=ORJSONResponse,
)
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_base_url], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(tbbm_router, prefix="/api")
app.include_router(tiktok_discovery_router, prefix="/api")


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request.complete",
        extra={"request_id": request_id, "service": "api", "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 2)},
    )
    return response


@app.get("/health")
def health() -> dict:
    return {"status": "healthy", "service": "api"}


@app.get("/ready")
def ready() -> dict:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ready"}
