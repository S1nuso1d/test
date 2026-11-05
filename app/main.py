from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from app.config import get_settings
from app.schemas import (
    BatchGenerationItem,
    BatchGenerationRequest,
    BatchGenerationResponse,
    CatalogImportResponse,
    GenerationResponse,
    PassportImportResponse,
    ModelBenchmarkItem,
    ModelBenchmarkRequest,
    ModelBenchmarkResponse,
    ProductInput,
)
from app.services.generator import GenerationError, generate_product_copy
from app.services.llm_client import LLMClient, LLMClientError, LLMConfigurationError
from app.services.render import to_markdown
from app.services.importers import MAX_UPLOAD_BYTES, parse_catalog_file, parse_passport_pdf

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Product Copy AI",
    description="Черновики B2B-карточек контрольно-измерительных приборов с помощью локальной LLM",
    version="0.9.2",
)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.9.2"}


@app.get("/api/status")
async def api_status() -> dict[str, str | int]:
    settings = get_settings()
    return {
        "provider": "Ollama (локально)",
        "model": settings.ollama_model,
        "base_url": settings.ollama_base_url,
        "max_batch_size": 10,
    }


@app.get("/api/models")
async def list_ollama_models() -> dict[str, str | list[str]]:
    settings = get_settings()
    try:
        return {
            "selected": settings.ollama_model,
            "models": await LLMClient(settings).list_models(),
        }
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/benchmark", response_model=ModelBenchmarkResponse)
async def benchmark_models(payload: ModelBenchmarkRequest) -> ModelBenchmarkResponse:
    """Run the same product through selected local models sequentially."""
    settings = get_settings()
    try:
        installed = await LLMClient(settings).list_models()
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    unavailable = [model for model in payload.models if model not in installed]
    if unavailable:
        raise HTTPException(
            status_code=422,
            detail=(
                "Следующие модели не установлены в Ollama: "
                + ", ".join(unavailable)
                + ". Сначала загрузите их командой ollama pull."
            ),
        )

    items: list[ModelBenchmarkItem] = []
    completed = 0
    failed = 0

    for model in payload.models:
        started = perf_counter()
        try:
            result = await generate_product_copy(
                payload.product,
                settings,
                model_name=model,
            )
            items.append(
                ModelBenchmarkItem(
                    model=model,
                    elapsed_seconds=round(perf_counter() - started, 2),
                    result=result,
                )
            )
            completed += 1
        except (LLMConfigurationError, LLMClientError, GenerationError) as exc:
            items.append(
                ModelBenchmarkItem(
                    model=model,
                    elapsed_seconds=round(perf_counter() - started, 2),
                    error=str(exc),
                )
            )
            failed += 1

    return ModelBenchmarkResponse(
        total=len(items),
        completed=completed,
        failed=failed,
        items=items,
    )


@app.post("/api/import/catalog", response_model=CatalogImportResponse)
async def import_catalog(file: UploadFile = File(...)) -> CatalogImportResponse:
    file_name = file.filename or "catalog.csv"
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    try:
        payload = parse_catalog_file(file_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CatalogImportResponse(
        imported_count=payload["imported_count"],
        products=payload["products"],
        warnings=payload["warnings"],
        errors=payload["errors"],
    )


@app.post("/api/import/passport", response_model=PassportImportResponse)
async def import_passport(file: UploadFile = File(...)) -> PassportImportResponse:
    file_name = file.filename or "passport.pdf"
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    try:
        payload = parse_passport_pdf(file_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PassportImportResponse(**payload)


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


@app.post("/api/generate/batch", response_model=BatchGenerationResponse)
async def generate_batch(payload: BatchGenerationRequest) -> BatchGenerationResponse:
    """Generate up to 10 products sequentially to avoid saturating a local model."""
    settings = get_settings()
    items: list[BatchGenerationItem] = []
    succeeded = 0
    failed = 0

    for index, product in enumerate(payload.products, start=1):
        try:
            result = await generate_product_copy(product, settings)
            items.append(
                BatchGenerationItem(index=index, product_name=product.name, result=result)
            )
            if result.status == "needs_data":
                failed += 1
            else:
                succeeded += 1
        except (LLMConfigurationError, LLMClientError, GenerationError) as exc:
            items.append(
                BatchGenerationItem(index=index, product_name=product.name, error=str(exc))
            )
            failed += 1

    return BatchGenerationResponse(
        total=len(items),
        succeeded=succeeded,
        failed=failed,
        items=items,
    )


@app.post("/api/export/markdown", response_class=PlainTextResponse)
async def export_markdown(result: GenerationResponse) -> PlainTextResponse:
    return PlainTextResponse(
        content=to_markdown(result),
        media_type="text/markdown; charset=utf-8",
    )
