from app.schemas import LLMProductCopy, ProductInput
from app.services.guardrails import (
    build_characteristics,
    build_safe_seo_description,
    build_source_text,
    calculate_quality_score,
    compact_seo_description,
    find_missing_data,
    find_unsupported_numbers,
    find_unsupported_unit_pairs,
    has_substantive_product_data,
    validate_generated_copy,
    validate_seo_description,
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


def test_number_guard_rejects_same_number_with_unsupported_unit() -> None:
    source = "Диапазон измерений 0–1,6 МПа; диаметр корпуса 100 мм."
    generated = "Диапазон измерений 0–1,6 бар; диаметр корпуса 100 мм."

    assert find_unsupported_numbers(generated, source) == []
    assert find_unsupported_unit_pairs(generated, source) == ["1.6 бар"]

    description = ("Текст для проверки выбора измерительного прибора. " * 16) + " Диапазон 1,6 бар."
    issues = validate_seo_description(description, source)
    assert any("неподтверждённые сочетания" in issue for issue in issues)


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
    issues = validate_generated_copy(draft, build_source_text(product))
    assert any("25" in issue for issue in issues)


def test_validation_enforces_description_length_and_query_count() -> None:
    product = ProductInput(name="Манометр DM 02", specs={"range": "0–1,6 МПа"})
    draft = _draft(seo_description="Короткий текст", seo_queries=["только один запрос"])
    issues = validate_generated_copy(draft, build_source_text(product))
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
    issues = validate_generated_copy(draft, build_source_text(product))
    assert any("25" in issue for issue in issues)



def test_safe_seo_fallback_meets_length_and_uses_only_source_numbers() -> None:
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
    description = build_safe_seo_description(product)
    assert 800 <= len(description) <= 1200
    assert find_unsupported_numbers(description, build_source_text(product)) == []


def test_formal_quality_score_is_not_a_semantic_accuracy_claim() -> None:
    draft = _draft()
    source = "Манометр DM 02. Диапазон 0–1,6 МПа."
    assert calculate_quality_score(draft, source) == 100

    short_draft = _draft(seo_description="Коротко")
    assert calculate_quality_score(short_draft, source) < 100

def test_unit_guard_does_not_treat_lowercase_russian_preposition_as_volt() -> None:
    source = "Длина кабельного вывода: 1 м."
    generated = "Длина кабельного вывода — 1 м. Перед заказом уточните сведения в паспорте."

    assert find_unsupported_unit_pairs(generated, source) == []


def test_unit_guard_still_recognizes_uppercase_cyrillic_volt() -> None:
    source = "Длина кабельного вывода: 1 м."
    generated = "Напряжение питания: 1 В."

    assert find_unsupported_unit_pairs(generated, source) == ["1 в"]


def test_number_guard_preserves_negative_range_boundary() -> None:
    unsupported = find_unsupported_numbers(
        "Рабочий диапазон температур 50…+250 °C.",
        "Рабочий диапазон температур −50…+250 °C.",
    )

    assert unsupported == ["50"]
 

def test_number_guard_accepts_temperature_range_spelled_out_with_sign_words() -> None:
    source = "Рабочий диапазон температур: −50…+250 °C."
    generated = "Рабочий диапазон температур — от минус 50 до плюс 250 градусов Цельсия."

    assert find_unsupported_numbers(generated, source) == []
    assert find_unsupported_unit_pairs(generated, source) == []


def test_pressure_transmitter_treats_current_output_as_present() -> None:
    product = ProductInput(
        name="ОВЕН ПД100-ДИ4,0-185-0,5",
        category="pressure_transmitter",
        specs={"Токовый выход": "4…20 мА, двухпроводная схема"},
    )

    report = find_missing_data(product)
    assert "Выходной сигнал" not in report.expected_specs


def test_overlong_seo_is_compacted_without_cutting_sentences_or_changing_facts() -> None:
    product = ProductInput(
        name="ОВЕН ПД100-ДИ4,0-185-0,5",
        manufacturer="ОВЕН",
        category="pressure_transmitter",
        description="Преобразователь давления для измерения давления в технологических системах.",
        specs={
            "Максимальное измеряемое давление": "4,0 МПа",
            "Основная приведённая погрешность": "0,5 % ВПИ",
            "Токовый выход": "4…20 мА, двухпроводная схема",
            "Напряжение питания": "12…36 В постоянного тока",
            "Температурный диапазон измеряемой среды": "−40…+100 °C",
            "Температурный диапазон окружающего воздуха": "−40…+80 °C",
            "Степень защиты корпуса": "IP65",
        },
    )
    sentences = [
        "ОВЕН ПД100-ДИ4,0-185-0,5 предназначен для измерения давления в технологических системах.",
        "Максимальное измеряемое давление составляет 4,0 МПа.",
        "Основная приведённая погрешность составляет 0,5 % ВПИ.",
        "Токовый выход — 4…20 мА по двухпроводной схеме.",
        "Напряжение питания — 12…36 В постоянного тока.",
        "Температурный диапазон измеряемой среды — от минус 40 до плюс 100 градусов Цельсия.",
        "Температурный диапазон окружающего воздуха — от минус 40 до плюс 80 градусов Цельсия.",
        "Степень защиты корпуса — IP65.",
    ]
    filler = [
        "Перед заказом уточните у поставщика состав комплекта и документы на выбранную модификацию.",
        "Сопоставьте параметры прибора с требованиями измерительного канала и проектной документацией.",
        "При необходимости запросите у поставщика сведения, которые не включены в исходную карточку.",
        "Перед закупкой проверьте, что техническое описание относится к точному обозначению модели.",
        "Дополнительные условия эксплуатации и монтажа уточните по паспорту конкретного исполнения.",
    ]
    long_description = " ".join(sentences + filler * 4)

    compacted = compact_seo_description(long_description, product)

    assert compacted is not None
    assert 800 <= len(compacted) <= 1200
    assert "4,0 МПа" in compacted
    assert "4…20 мА" in compacted
    assert "от минус 40 до плюс 100 градусов Цельсия" in compacted
    assert "от минус 40 до плюс 80 градусов Цельсия" in compacted
    assert not validate_seo_description(compacted, build_source_text(product), product)



def test_safe_seo_fallback_uses_product_copy_style() -> None:
    product = ProductInput(
        name="ОВЕН ДТС024-100П.В3.30/1 — термопреобразователь сопротивления",
        manufacturer="ОВЕН",
        category="temperature_sensor",
        specs={
            "Номинальная статическая характеристика (НСХ)": "100П",
            "Длина кабельного вывода": "1 м",
            "Рабочий диапазон измеряемых температур": "−50…+250 °C",
            "Степень защиты датчика": "IP54",
        },
        description=(
            "ОВЕН ДТС024-100П.В3.30/1 — термопреобразователь сопротивления "
            "для непрерывного измерения температуры рабочих сред."
        ),
    )
    description = build_safe_seo_description(product)

    assert 800 <= len(description) <= 1200
    assert "В исходных данных указан товар" not in description
    assert "В карточке приведены характеристики" not in description
    assert "Прибор предназначен для непрерывного измерения" in description
    assert description.count("ОВЕН ДТС024-100П.В3.30/1") == 1
    assert ".. " not in description
    assert "Ключевые параметры исполнения" in description


def test_unit_guard_does_not_join_a_number_to_the_next_line_initial() -> None:
    source = "Количество чувствительных элементов — 1 шт."
    generated = "Количество чувствительных элементов — 1\nВ описании также приведены параметры."

    assert find_unsupported_unit_pairs(generated, source) == []
