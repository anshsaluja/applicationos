from fastapi import FastAPI

from .api import router

app = FastAPI(
    title="ApplicationOS API",
    version="0.1.0",
    description="Agentic workflow API for complex application processes.",
)
app.include_router(router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
