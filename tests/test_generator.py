from app.config import Settings
from app.schemas import ProductInput
from app.services.generator import generate_product_copy


PRODUCT = ProductInput(
    name="Манометр показывающий DM 02",
    manufacturer="Манотомь",
    specs={
        "диапазон измерений": "0–1,6 МПа",
        "класс точности": "1,5",
        "присоединение": "G1/2",
        "диаметр корпуса": "100 мм",
    },
    description="Прибор предназначен для измерения избыточного давления.",
)


def good_response(**overrides):
    description = (
        "Манометр показывающий DM 02 производства Манотомь предназначен для измерения "
        "избыточного давления. В исходных данных указан диапазон измерений 0–1,6 МПа. "
        "При подборе прибора этот диапазон необходимо сопоставить с ожидаемым давлением "
        "в измерительной точке и требованиями технологического процесса. Класс точности "
        "указан как 1,5; его следует сравнить с требованиями задачи измерения и правилами "
        "эксплуатации оборудования. Присоединение обозначено как G1/2, поэтому перед "
        "монтажом нужно сверить это обозначение с ответной частью узла. Диаметр корпуса "
        "составляет 100 мм; это значение следует проверить относительно пространства для "
        "установки и условий считывания показаний. Во входных данных не приведены сведения "
        "о материалах исполнения, степени защиты, температурных ограничениях и комплекте "
        "поставки. Если эти параметры важны для выбора, их следует запросить в техническом "
        "паспорте или у производителя. Описание не подтверждает совместимость с конкретной "
        "системой, рабочей средой или условиями эксплуатации. Перед публикацией карточки "
        "необходимо сверить наименование и все указанные параметры с документацией товара."
    )
    data = {
        "seo_title": "Манометр показывающий DM 02 Манотомь",
        "seo_description": description[:1050].ljust(800, " "),
        "seo_queries": [
            "манометр показывающий DM 02",
            "манометр Манотомь",
            "манометр диапазон 0–1,6 МПа",
        ],
        "sales_section": {
            "suitable_for": ["Специалисты по подбору приборов измерения давления"],
            "tasks_solved": ["Измерение избыточного давления, указанное в описании прибора"],
            "pitch": "Перед подбором следует сверить диапазон, точность, присоединение и размеры с документацией производителя.",
        },
    }
    data.update(overrides)
    return data


async def test_generator_returns_source_characteristics_and_sales_section(monkeypatch) -> None:
    async def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        return good_response()

    monkeypatch.setattr("app.services.generator.LLMClient.generate_json", fake_generate_json)
    result = await generate_product_copy(PRODUCT, Settings())

    assert result.status == "generated"
    assert result.seo_title == "Манометр показывающий DM 02 Манотомь"
    assert result.key_characteristics[0].value == "0–1,6 МПа"
    assert 800 <= len(result.seo_description or "") <= 1200
    assert result.sales_section is not None
    assert result.commercial_block and "Кому подходит" in result.commercial_block
    assert result.attempts == 1


async def test_generator_retries_and_recovers_from_short_description(monkeypatch) -> None:
    responses = [
        good_response(seo_description="Слишком короткое описание."),
        good_response(),
    ]
    calls = 0
    prompts: list[str] = []

    async def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        nonlocal calls
        prompts.append(user_prompt)
        response = responses[calls]
        calls += 1
        return response

    monkeypatch.setattr("app.services.generator.LLMClient.generate_json", fake_generate_json)
    result = await generate_product_copy(PRODUCT, Settings())

    assert result.status == "generated"
    assert calls == 2
    assert "800–1200" in prompts[1]
    assert result.attempts == 2


async def test_generator_returns_needs_review_after_three_invalid_results(monkeypatch) -> None:
    calls = 0

    async def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        nonlocal calls
        calls += 1
        return good_response(seo_description="Слишком короткий SEO-текст.")

    monkeypatch.setattr("app.services.generator.LLMClient.generate_json", fake_generate_json)
    result = await generate_product_copy(PRODUCT, Settings())

    assert calls == 3
    assert result.status == "needs_review"
    assert result.attempts == 3
    assert result.validation_errors
    assert result.seo_description == "Слишком короткий SEO-текст."
    assert any("не должна считаться готовой" in warning for warning in result.warnings)


async def test_generator_retries_unsupported_number_in_search_query(monkeypatch) -> None:
    responses = [
        good_response(seo_queries=["манометр 25 бар", "манометр DM 02", "манометр давления"]),
        good_response(),
    ]
    calls = 0

    async def fake_generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        nonlocal calls
        response = responses[calls]
        calls += 1
        return response

    monkeypatch.setattr("app.services.generator.LLMClient.generate_json", fake_generate_json)
    result = await generate_product_copy(PRODUCT, Settings())

    assert calls == 2
    assert result.status == "generated"
    assert result.attempts == 2


async def test_generator_does_not_call_llm_without_substantive_data(monkeypatch) -> None:
    async def fail_if_called(self, system_prompt: str, user_prompt: str) -> dict:
        raise AssertionError("LLM should not be called for empty input")

    monkeypatch.setattr("app.services.generator.LLMClient.generate_json", fail_if_called)
    result = await generate_product_copy(ProductInput(name="Манометр DM 02"), Settings())
    assert result.status == "needs_data"
    assert result.attempts == 0
