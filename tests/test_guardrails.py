from app.schemas import LLMProductCopy, ProductInput, SalesSection
from app.services.guardrails import (
    build_characteristics,
    find_missing_data,
    find_unsupported_numbers,
    has_substantive_product_data,
    validate_generated_copy,
)


def test_pressure_gauge_template_does_not_request_power_supply() -> None:
    product = ProductInput(
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

    report = find_missing_data(product)
    assert report.category == "pressure_gauge"
    assert report.expected_specs == []
    assert "Напряжение питания" not in report.expected_specs


def test_temperature_transmitter_reports_category_specific_missing_fields() -> None:
    product = ProductInput(
        name="Преобразователь температуры TP-200",
        specs={
            "диапазон измерений": "-50...+200 °C",
            "выходной сигнал": "4–20 мА",
            "класс точности": "0,5",
        },
        description="Преобразователь сигнала термопреобразователя сопротивления.",
    )

    report = find_missing_data(product)
    assert report.category == "temperature_transmitter"
    assert "Напряжение питания" in report.expected_specs
    assert "Выходной сигнал" not in report.expected_specs


def test_empty_expected_spec_is_not_reported_twice() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"диапазон измерений": "", "класс точности": "1,5"},
    )
    report = find_missing_data(product)
    assert report.empty_specs == ["диапазон измерений"]
    assert "Диапазон измерений" not in report.expected_specs


def test_characteristics_copy_source_and_add_missing_expected_spec() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"диапазон измерений": "0–1,6 МПа"},
    )
    report = find_missing_data(product)
    rows = build_characteristics(product, report)
    values = {row.name: row.value for row in rows}
    assert values["диапазон измерений"] == "0–1,6 МПа"
    assert values["Класс точности"] == "данных нет"


def test_unknown_category_does_not_apply_generic_spec_template() -> None:
    product = ProductInput(name="Неизвестный прибор", specs={"параметр": "значение"})
    report = find_missing_data(product)
    assert report.category == "generic"
    assert report.expected_specs == []


def test_missing_fields_and_substantive_data() -> None:
    product = ProductInput(name="Манометр DM 02")
    report = find_missing_data(product)
    assert "manufacturer" in report.fields
    assert "description" in report.fields
    assert has_substantive_product_data(product) is False


def test_number_guard_finds_unsupported_numbers() -> None:
    unsupported = find_unsupported_numbers(
        "Диапазон 0–1,6 МПа, диаметр корпуса 150 мм.",
        "Диапазон 0–1,6 МПа; диаметр корпуса 100 мм.",
    )
    assert unsupported == ["150"]


def test_number_guard_accepts_decimal_comma_or_point() -> None:
    unsupported = find_unsupported_numbers(
        "Класс точности 1.5, диаметр 100 мм.",
        "Класс точности 1,5; диаметр 100 мм.",
    )
    assert unsupported == []


def _draft(**overrides) -> LLMProductCopy:
    description = "Текст описания без числовых значений, основанный на предоставленных фактах. " * 12
    data = {
        "seo_title": "Манометр показывающий DM 02",
        "seo_description": description[:900],
        "seo_queries": ["манометр DM 02", "манометр Манотомь", "манометр давления"],
        "sales_section": {
            "suitable_for": ["Специалисты, подбирающие приборы измерения давления"],
            "tasks_solved": ["Измерение избыточного давления, указанное в описании товара"],
            "pitch": "Перед подбором следует сверить характеристики с документацией производителя.",
        },
    }
    data.update(overrides)
    return LLMProductCopy.model_validate(data)


def test_number_guard_checks_search_queries_and_sales_block_too() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"диапазон": "0–1,6 МПа"},
        description="Манометр для измерения давления.",
    )
    draft = _draft(seo_queries=["манометр 25 бар", "манометр DM 02", "манометр давления"])
    issues = validate_generated_copy(draft, "\n".join([product.name or "", product.description or "", "диапазон: 0–1,6 МПа"]))
    assert any("25" in issue for issue in issues)


def test_validation_enforces_description_length_and_query_count() -> None:
    product = ProductInput(name="Манометр DM 02", specs={"range": "0–1,6 МПа"})
    draft = _draft(seo_description="Короткий текст", seo_queries=["только один запрос"])
    issues = validate_generated_copy(draft, "Манометр DM 02 range 0–1,6 МПа")
    assert any("800–1200" in issue for issue in issues)
    assert any("3–5" in issue for issue in issues)


def test_number_guard_checks_sales_audience_and_pitch() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"диапазон измерений": "0–1,6 МПа"},
        description="Прибор для измерения давления.",
    )
    draft = _draft(
        sales_section={
            "suitable_for": ["Покупатели оборудования с параметром 25 бар"],
            "tasks_solved": ["Измерение давления"],
            "pitch": "Сверьте параметры с документацией.",
        }
    )
    source = "Манометр DM 02. Диапазон измерений 0–1,6 МПа. Прибор для измерения давления."
    issues = validate_generated_copy(draft, source)
    assert any("25" in issue for issue in issues)
