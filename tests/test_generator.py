from app.config import Settings
from app.schemas import ProductInput
from app.services.generator import generate_product_copy


async def test_generator_returns_source_characteristics(monkeypatch) -> None:
    description = (
        "Прибор описан на основании предоставленных исходных сведений. "
        "Перед публикацией контент-менеджеру следует сверить назначение, "
        "условия эксплуатации, комплект поставки и совместимость с паспортом. "
        "Если такие сведения отсутствуют, их необходимо запросить у производителя. "
    ) * 5
    description = description[:900]

    async def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        return {
            "seo_title": "Манометр показывающий DM 02 Манотомь",
            "seo_description": description,
            "seo_queries": [
                "манометр показывающий DM 02",
                "манометр Манотомь",
                "манометр для измерения давления",
            ],
            "commercial_block": (
                "Для определения целевой аудитории и задач применения нужно уточнить "
                "условия эксплуатации и назначение по техническому паспорту."
            ),
        }

    monkeypatch.setattr(
        "app.services.generator.LLMClient.generate_json",
        fake_generate_json,
    )
    product = ProductInput(
        name="Манометр показывающий DM 02",
        manufacturer="Манотомь",
        specs={"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5"},
        description="Прибор предназначен для измерения избыточного давления.",
    )

    result = await generate_product_copy(product, Settings())

    assert result.status == "generated"
    assert result.seo_title == "Манометр показывающий DM 02 Манотомь"
    assert result.key_characteristics[0].value == "0–1,6 МПа"
    assert len(result.seo_description or "") == 900


async def test_generator_retries_when_seo_description_is_too_short(monkeypatch) -> None:
    valid_description = (
        "Описание составлено только по предоставленным сведениям о товаре. "
        "Перед публикацией необходимо проверить паспорт, комплект поставки и "
        "дополнительные параметры, которые не были переданы во входных данных. "
    ) * 6
    valid_description = valid_description[:900]
    responses = [
        {
            "seo_title": "Манометр DM 02",
            "seo_description": "Слишком короткое описание.",
            "seo_queries": ["манометр DM 02", "манометр Манотомь", "манометр"],
            "commercial_block": "Назначение следует уточнить по паспорту.",
        },
        {
            "seo_title": "Манометр DM 02",
            "seo_description": valid_description,
            "seo_queries": ["манометр DM 02", "манометр Манотомь", "манометр"],
            "commercial_block": "Назначение следует уточнить по паспорту.",
        },
    ]
    calls = 0

    async def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        nonlocal calls
        result = responses[calls]
        calls += 1
        return result

    monkeypatch.setattr(
        "app.services.generator.LLMClient.generate_json",
        fake_generate_json,
    )
    product = ProductInput(
        name="Манометр DM 02",
        manufacturer="Манотомь",
        specs={"диапазон измерений": "0–1,6 МПа"},
        description="Манометр для измерения избыточного давления.",
    )

    result = await generate_product_copy(product, Settings())

    assert result.status == "generated"
    assert calls == 2
    assert result.seo_description == valid_description.strip()
