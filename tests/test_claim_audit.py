from app.schemas import LLMProductCopy, ProductInput
from app.services.guardrails import validate_generated_copy, validate_seo_description
from app.services.claim_audit import audit_draft_claims, audit_spec_value_mismatches, audit_text_claims


def test_unprovided_explosion_protection_is_critical() -> None:
    findings = audit_text_claims(
        "Прибор имеет взрывозащищённое исполнение.",
        "Манометр DM 02. Диапазон измерений 0–1,6 МПа.",
        "SEO-описание",
    )

    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert findings[0].category == "Взрывозащита"


def test_claim_is_not_flagged_when_the_same_fact_is_in_source() -> None:
    findings = audit_text_claims(
        "Корпус выполнен из нержавеющей стали, степень защиты IP65.",
        "Материал корпуса — нержавеющая сталь; степень защиты IP65.",
        "SEO-описание",
    )

    assert findings == []


def test_claim_audit_checks_commercial_block_and_queries() -> None:
    draft = LLMProductCopy.model_validate(
        {
            "seo_title": "Манометр DM 02",
            "seo_description": "Описание товара без спорных утверждений.",
            "seo_queries": ["манометр с дисплеем", "манометр DM 02", "манометр давления"],
            "sales_section": {
                "suitable_for": ["Для пищевой промышленности"],
                "tasks_solved": ["Измерение давления"],
                "pitch": "Устройство имеет беспроводную связь.",
            },
        }
    )

    findings = audit_draft_claims(draft, "Манометр DM 02 для измерения давления.")
    assert {item.field for item in findings} == {
        "Поисковые запросы",
        "Кому подходит",
        "Тезисы для менеджера",
    }
    assert {item.category for item in findings} == {
        "Дисплей или индикация",
        "Пищевая или санитарная совместимость",
        "Беспроводная связь",
    }


def test_explicit_absence_disclaimer_is_not_flagged() -> None:
    findings = audit_text_claims(
        "Степень защиты IP в исходных данных не указана.",
        "Манометр DM 02.",
        "SEO-описание",
    )

    assert findings == []



def test_generation_validator_returns_claim_findings_and_rejects_duplicated_queries() -> None:
    draft = LLMProductCopy.model_validate(
        {
            "seo_title": "Манометр DM 02",
            "seo_description": "Описание товара без дополнительных чисел. " * 23,
            "seo_queries": [
                "манометр DM 02",
                "Манометр, DM 02!",
                "манометр для измерения давления",
            ],
            "sales_section": {
                "suitable_for": ["Для специалистов КИПиА"],
                "tasks_solved": ["Измерение давления"],
                "pitch": "Прибор имеет взрывозащищённое исполнение.",
            },
        }
    )

    issues = validate_generated_copy(draft, "Манометр DM 02. Измерение давления.")
    assert any("повторы" in issue for issue in issues)
    assert any("Взрывозащита" in issue for issue in issues)


def test_seo_validator_flags_unprovided_ip_protection() -> None:
    description = "Описание товара для проверки требований к выбору. " * 17
    description += " Устройство имеет степень защиты IP65."
    issues = validate_seo_description(description, "Манометр DM 02.")
    assert any("Степень защиты IP" in issue for issue in issues)


def test_seo_validator_does_not_flag_buyer_checklist_as_claim() -> None:
    description = (
        "Перед выбором уточните наличие сертификата и проверьте сведения о поверке. "
        * 20
    )
    findings = audit_text_claims(description, "Манометр DM 02.", "SEO-описание")
    assert findings == []



def test_ip_audit_rejects_a_different_code_when_source_has_one() -> None:
    findings = audit_text_claims(
        "Степень защиты прибора — IP54.",
        "Степень защиты: IP65.",
        "SEO-описание",
    )
    assert len(findings) == 1
    assert findings[0].category == "Степень защиты IP"


def test_spec_audit_detects_diameter_value_swap() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"Диаметр корпуса": "100 мм"},
    )
    findings = audit_spec_value_mismatches(
        "Диаметр корпуса составляет 200 мм.",
        product,
        "SEO-описание",
    )
    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert "100 мм" in findings[0].message


def test_spec_audit_detects_unit_substitution_for_same_number() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"Диапазон измерений": "0–1,6 МПа"},
    )
    findings = audit_spec_value_mismatches(
        "Диапазон измерений: 0–1,6 бар.",
        product,
        "SEO-описание",
    )
    assert len(findings) == 1
    assert "0–1,6 МПа" in findings[0].message



def test_spec_audit_handles_inflected_range_label_and_keeps_full_context() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"Диапазон измерений": "0–1,6 МПа"},
    )
    findings = audit_spec_value_mismatches(
        "Для специалистов с диапазоном измерений до 1,6 МПа.",
        product,
        "Кому подходит",
    )

    assert len(findings) == 1
    assert findings[0].category == "Диапазон измерений"
    assert "диапазоном измерений" in findings[0].claim.casefold()
    assert not findings[0].claim.startswith("ом")
    assert "0–1,6 МПа" in findings[0].message


def test_spec_audit_accepts_complete_range_with_inflected_label() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"Диапазон измерений": "0–1,6 МПа"},
    )
    findings = audit_spec_value_mismatches(
        "Прибор работает с диапазоном измерений от 0 до 1,6 МПа.",
        product,
        "SEO-описание",
    )
    assert findings == []


def test_spec_audit_distinguishes_temperature_range_from_measurement_range() -> None:
    product = ProductInput(
        name="Термодатчик",
        specs={
            "Диапазон измерений": "0–100 °C",
            "Диапазон температуры": "−20–60 °C",
        },
    )
    findings = audit_spec_value_mismatches(
        "Диапазон температуры составляет −10–60 °C.",
        product,
        "SEO-описание",
    )

    assert len(findings) == 1
    assert findings[0].category == "Диапазон температуры"


def test_validation_rejects_technical_specification_in_suitable_for() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"Диапазон измерений": "0–1,6 МПа"},
    )
    draft = LLMProductCopy.model_validate(
        {
            "seo_title": "Манометр DM 02",
            "seo_description": "Черновик описания.",
            "seo_queries": ["манометр DM 02", "манометр давления", "манометр Манотомь"],
            "sales_section": {
                "suitable_for": ["Для специалистов с диапазоном измерений до 1,6 МПа"],
                "tasks_solved": ["Измерение давления"],
                "pitch": "Перед покупкой проверьте параметры по паспорту.",
            },
        }
    )

    issues = validate_generated_copy(
        draft,
        "Манометр DM 02. Диапазон измерений: 0–1,6 МПа.",
        product,
    )
    assert any("Поле «Кому подходит»" in issue for issue in issues)


def test_validation_accepts_audience_without_technical_specification() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"Диапазон измерений": "0–1,6 МПа"},
    )
    draft = LLMProductCopy.model_validate(
        {
            "seo_title": "Манометр DM 02",
            "seo_description": "Черновик описания.",
            "seo_queries": ["манометр DM 02", "манометр давления", "манометр Манотомь"],
            "sales_section": {
                "suitable_for": ["Специалисты по КИПиА"],
                "tasks_solved": ["Измерение избыточного давления"],
                "pitch": "Перед покупкой проверьте параметры по паспорту.",
            },
        }
    )

    issues = validate_generated_copy(
        draft,
        "Манометр DM 02. Диапазон измерений: 0–1,6 МПа.",
        product,
    )
    assert not any("Поле «Кому подходит»" in issue for issue in issues)
