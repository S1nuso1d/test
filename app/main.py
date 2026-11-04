from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.schemas import GenerationResponse, ProductInput
from app.services.generator import GenerationError, generate_product_copy
from app.services.llm_client import LLMClient, LLMClientError, LLMConfigurationError

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Product Copy AI",
    description="Черновики B2B-карточек контрольно-измерительных приборов с помощью локальной LLM",
    version="0.3.0",
)
if (BASE_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def api_status() -> dict[str, str]:
    settings = get_settings()
    return {
        "provider": "Ollama (локально)",
        "model": settings.ollama_model,
        "base_url": settings.ollama_base_url,
    }


@app.post("/api/test-connection")
async def test_ollama_connection() -> dict[str, str]:
    settings = get_settings()
    try:
        reply = await LLMClient(settings).test_connection()
        return {
            "status": "ok",
            "provider": "Ollama",
            "model": settings.ollama_model,
            "reply": reply,
        }
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/generate", response_model=GenerationResponse)
async def generate(product: ProductInput) -> GenerationResponse:
    settings = get_settings()
    try:
        return await generate_product_copy(product, settings)
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (LLMClientError, GenerationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
