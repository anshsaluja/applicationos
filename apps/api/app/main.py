from fastapi import FastAPI

app = FastAPI(
    title="ApplicationOS API",
    version="0.1.0",
    description="Agentic workflow API for complex application processes.",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
