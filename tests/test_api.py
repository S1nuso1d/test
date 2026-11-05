from fastapi.testclient import TestClient

from app.main import app
from app.services.generator import GenerationError
from app.schemas import GenerationResponse, ProductInput

client = TestClient(app)


def _result(product: ProductInput) -> GenerationResponse:
    return GenerationResponse(
        status="generated",
        product_name=product.name,
        manufacturer=product.manufacturer,
        seo_title="Тестовый заголовок",
        seo_description="Тестовое описание",
        seo_queries=["запрос 1", "запрос 2", "запрос 3"],
        commercial_block="Коммерческий блок",
        missing_fields=[],
        warnings=["Черновик"],
        attempts=1,
    )


def test_batch_endpoint_processes_items_and_keeps_per_item_results(monkeypatch) -> None:
    async def fake_generate(product, settings):
        return _result(product)

    monkeypatch.setattr("app.main.generate_product_copy", fake_generate)
    response = client.post(
        "/api/generate/batch",
        json={"products": [{"name": "Товар A"}, {"name": "Товар B"}]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert payload["items"][1]["product_name"] == "Товар B"


def test_batch_endpoint_limits_batch_size() -> None:
    response = client.post(
        "/api/generate/batch",
        json={"products": [{"name": f"Товар {i}"} for i in range(11)]},
    )
    assert response.status_code == 422


def test_markdown_export_endpoint() -> None:
    response = client.post(
        "/api/export/markdown",
        json={
            "status": "needs_review",
            "product_name": "Манометр DM 02",
            "seo_title": "Манометр DM 02",
            "seo_description": "Короткий текст",
            "seo_queries": ["манометр DM 02"],
            "commercial_block": "Проверить паспорт",
            "validation_errors": ["SEO-описание содержит 13 символов; требуется 800–1200"],
            "attempts": 3,
        },
    )
    assert response.status_code == 200
    assert "Манометр DM 02" in response.text
    assert "Ошибки проверки" in response.text
    assert "needs_review" in response.text


def test_batch_endpoint_continues_after_one_item_failure(monkeypatch) -> None:
    async def fake_generate(product, settings):
        if product.name == "Сломанный товар":
            raise GenerationError("ошибка тестового генератора")
        return _result(product)

    monkeypatch.setattr("app.main.generate_product_copy", fake_generate)
    response = client.post(
        "/api/generate/batch",
        json={"products": [{"name": "Сломанный товар"}, {"name": "Товар B"}]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["succeeded"] == 1
    assert payload["failed"] == 1
    assert payload["items"][0]["error"] == "ошибка тестового генератора"
    assert payload["items"][1]["result"]["product_name"] == "Товар B"
