import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.rate_limit import AuthRateLimiter

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("onda.api")

app = FastAPI(
    title=settings.app_name,
    summary="Secure messaging, meeting and calling API for Onda.",
    version="0.2.0",
    docs_url="/docs" if settings.environment != "production" or settings.enable_docs else None,
    redoc_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
auth_rate_limiter = AuthRateLimiter(settings.auth_rate_limit_per_minute)


@app.middleware("http")
async def authentication_rate_limit(request: Request, call_next):
    return await auth_rate_limiter(request, call_next)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid4()))[:128]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    logger.info(
        "request_completed method=%s path=%s status=%s duration_ms=%.2f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
        request_id,
    )
    return response


app.include_router(api_router, prefix=settings.api_v1_prefix)
