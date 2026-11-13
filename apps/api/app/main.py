import os
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy import text as sql_text

from .api import router
from .persistence import build_engine

app = FastAPI(
    title="ApplicationOS API",
    version="0.1.0",
    description="Agentic workflow API for complex application processes.",
)

def parse_cors_origins(value: str) -> list[str]:
    """Allow only explicit HTTP(S) browser origins, never wildcards or URL paths."""
    origins: list[str] = []
    for item in value.split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        # Backslashes and controls have inconsistent URL interpretations across clients.\n        if any(ch == "\\\\" or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in origin):\n            raise ValueError("CORS_ALLOWED_ORIGINS contains unsafe URL characters")\n        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in origin\n            or (parsed.netloc.endswith(":") and not parsed.netloc.endswith("]:"))
        ):
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit HTTP(S) origins")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("CORS_ALLOWED_ORIGINS contains an invalid port") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("CORS_ALLOWED_ORIGINS contains an invalid port")
        if origin not in origins:
            origins.append(origin)
    return origins


# Explicit origins only: reject unsafe configuration rather than silently broadening access.
origins = parse_cors_origins(os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Review-Token"],
)
app.include_router(router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def readiness() -> Response:
    """Check database connectivity without exposing connection details.

    Liveness (/health) intentionally remains independent of PostgreSQL.
    Readiness must fail closed when durable storage is unavailable.
    """
    from fastapi.responses import JSONResponse

    engine = None
    try:
        engine = build_engine()
        with engine.connect() as connection:
            connection.execute(sql_text("SELECT 1"))
    except Exception:  # noqa: BLE001 - readiness must fail closed for any DB setup/driver error
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    finally:
        if engine is not None:
            engine.dispose()
    return JSONResponse(content={"status": "ready"})


@app.middleware("http")
async def harden_api_responses(request: Request, call_next) -> Response:
    """Prevent caching sensitive documents and workflow state in shared caches."""
    response = await call_next(request)
    # Generate IDs server-side; never echo untrusted client-provided correlation values.
    response.headers["X-Request-ID"] = str(uuid4())
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path.startswith("/v1/"):
        response.headers["Cache-Control"] = "no-store"
    return response
