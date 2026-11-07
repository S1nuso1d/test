from app.schemas import LLMProductCopy, ProductInput
from app.services.guardrails import validate_generated_copy, validate_seo_description
from app.services.claim_audit import (
    audit_draft_claims,
    audit_spec_value_mismatches,
    audit_text_claims,
    drop_flagged_sentences,
)


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

def test_search_query_may_omit_temperature_unit_without_flagging_range() -> None:
    product = ProductInput(
        name="ОВЕН ДТС024-100П.В3.30/1",
        specs={"Рабочий диапазон измеряемых температур для НСХ 50П/100П/Pt100": "−50…+250 °C"},
    )

    findings = audit_spec_value_mismatches(
        "датчик температуры ОВЕН диапазон -50 до +250",
        product,
        "Поисковые запросы",
        allow_missing_units=True,
    )

    assert findings == []


def test_search_query_still_rejects_an_explicitly_wrong_temperature_unit() -> None:
    product = ProductInput(
        name="ОВЕН ДТС024-100П.В3.30/1",
        specs={"Рабочий диапазон измеряемых температур для НСХ 50П/100П/Pt100": "−50…+250 °C"},
    )

    findings = audit_spec_value_mismatches(
        "датчик температуры ОВЕН диапазон -50 до +250 °F",
        product,
        "Поисковые запросы",
        allow_missing_units=True,
    )

    assert len(findings) == 1
    assert findings[0].severity == "critical"


def test_fact_audit_flags_unsupported_marketing_promises() -> None:
    findings = audit_text_claims(
        "Прибор обеспечивает надёжное измерение и удобную интеграцию в систему управления.",
        "Термопреобразователь сопротивления для измерения температуры.",
        "SEO-описание",
    )

    categories = {finding.category for finding in findings}
    assert "Неподтверждённые преимущества" in categories
    assert "Совместимость и интеграция" in categories


def test_fact_audit_does_not_flag_installation_checklist_as_product_claim() -> None:
    findings = audit_text_claims(
        "Перед заказом проверьте требования к монтажу и интеграции по паспорту изделия.",
        "Термопреобразователь сопротивления.",
        "SEO-описание",
    )

    assert findings == []

def test_temperature_medium_and_ambient_ranges_are_compared_separately() -> None:
    product = ProductInput(
        name="ОВЕН ПД100",
        specs={
            "Температурный диапазон измеряемой среды": "−40…+100 °C",
            "Температурный диапазон окружающего воздуха": "−40…+80 °C",
        },
    )
    text = (
        "Температурный диапазон измеряемой среды — от минус 40 до плюс 100 градусов Цельсия. "
        "Температурный диапазон окружающего воздуха — от минус 40 до плюс 80 °C."
    )

    assert audit_spec_value_mismatches(text, product, "SEO-описание") == []


def test_temperature_range_audit_still_detects_swapped_ambient_value() -> None:
    product = ProductInput(
        name="ОВЕН ПД100",
        specs={
            "Температурный диапазон измеряемой среды": "−40…+100 °C",
            "Температурный диапазон окружающего воздуха": "−40…+80 °C",
        },
    )
    text = (
        "Температурный диапазон измеряемой среды — от минус 40 до плюс 100 °C. "
        "Температурный диапазон окружающего воздуха — от минус 40 до плюс 100 °C."
    )

    findings = audit_spec_value_mismatches(text, product, "SEO-описание")
    assert len(findings) == 1
    assert findings[0].category == "Температурный диапазон окружающего воздуха"


def test_compatibility_checklist_is_not_a_positive_claim() -> None:
    findings = audit_text_claims(
        "Перед выбором уточните совместимость с системой управления и проверьте возможность интеграции.",
        "Преобразователь давления с токовым выходом 4…20 мА.",
        "SEO-описание",
    )

    assert findings == []


def test_positive_compatibility_and_integration_claims_are_flagged() -> None:
    findings = audit_text_claims(
        "Прибор полностью совместим с системой заказчика и обеспечивает простую интеграцию.",
        "Преобразователь давления с токовым выходом 4…20 мА.",
        "SEO-описание",
    )

    assert {finding.category for finding in findings} == {"Совместимость и интеграция"}



def test_one_source_word_does_not_excuse_other_advertising_words() -> None:
    findings = audit_text_claims(
        "Надёжный датчик, проверьте паспорт.",
        "Универсальный термопреобразователь сопротивления.",
        "SEO-описание",
    )
    assert {finding.category for finding in findings} == {"Неподтверждённые преимущества"}


def test_negated_aggressive_media_in_source_does_not_confirm_aggressive_environments() -> None:
    source = "Среды: пар, газ, если они не агрессивны к материалу корпуса датчика."
    findings = audit_text_claims("Датчик для работы в агрессивных средах.", source, "SEO-описание")
    assert [finding.category for finding in findings] == ["Стойкость к агрессивной среде"]


def test_advertising_claim_is_not_excused_by_a_checklist_phrase() -> None:
    findings = audit_text_claims(
        "Датчик рассчитан на тяжёлые условия эксплуатации; сверьте это с паспортом.",
        "Термопреобразователь сопротивления.",
        "SEO-описание",
    )
    assert findings


def test_confirmed_warranty_and_climate_resistance_are_not_flagged() -> None:
    source = "Гарантия: 12 мес. Устойчивость к климатическим воздействиям: УХЛ 3.1."
    assert audit_text_claims("Гарантия производителя 12 мес.", source, "SEO-описание") == []
    assert audit_text_claims(
        "Устойчивость к климатическим воздействиям УХЛ 3.1.", source, "SEO-описание"
    ) == []


def test_drop_flagged_sentences_removes_only_unconfirmed_sentences() -> None:
    text = "Прибор измеряет давление. Надёжный датчик для агрессивных сред. Диапазон 0–1,6 МПа."
    cleaned = drop_flagged_sentences(
        text, "Манометр. диапазон: 0–1,6 МПа", None, "SEO-описание"
    )
    assert cleaned == "Прибор измеряет давление. Диапазон 0–1,6 МПа."


def test_lost_qualifier_is_detected() -> None:
    from app.services.guardrails import find_lost_qualifiers

    product = ProductInput(name="X", specs={"Потребляемая мощность": "не более 0,8 Вт"})
    assert find_lost_qualifiers("Потребляемая мощность 0,8 Вт.", product)
    assert not find_lost_qualifiers("Потребляемая мощность не более 0,8 Вт.", product)



def test_audit_flags_humidity_dust_and_pressure_load_relabeling() -> None:
    source = (
        "Максимальное измеряемое давление: 4,0 МПа. "
        "Степень защиты корпуса: IP65."
    )
    generated = (
        "Работа в условиях повышенной влажности и пыли. "
        "Прибор рассчитан на максимальную нагрузку 4,0 МПа."
    )
    findings = audit_text_claims(generated, source, "Решаемые задачи")
    assert {finding.category for finding in findings} == {
        "Повышенная влажность и пыль",
        "Подмена измеряемого давления нагрузкой",
    }


def test_audit_flags_unconfirmed_stable_indication_and_installation_location() -> None:
    findings = audit_text_claims(
        "Стабильная индикация давления на панели управления.",
        "Манометр DM 02 для измерения давления.",
        "SEO-описание",
    )
    assert {finding.category for finding in findings} == {
        "Неподтверждённые преимущества",
        "Объект или место установки",
    }


def test_integrating_verb_is_checked_as_compatibility_claim() -> None:
    findings = audit_text_claims(
        "Конструкция позволяет интегрировать прибор в трубопровод.",
        "Манометр с присоединением G1/2.",
        "SEO-описание",
    )
    assert any(item.category == "Совместимость и интеграция" for item in findings)


def test_flange_claim_is_flagged_when_source_only_says_g_half() -> None:
    findings = audit_text_claims(
        "Присоединение G1/2 позволяет установить прибор на стандартные фланцевые соединения.",
        "Манометр DM 02. Присоединение: G1/2.",
        "Тезисы для менеджера",
    )
    assert any(item.category == "Фланцевое присоединение" for item in findings)


def test_housing_material_is_not_inferred_from_protective_armature_material() -> None:
    findings = audit_text_claims(
        "Корпус прибора выполнен из стали 12Х18Н10Т.",
        "Материал защитной арматуры для модели 024: сталь 12Х18Н10Т.",
        "SEO-описание",
    )
    assert any(
        item.category == "Материал корпуса перепутан с материалом защитной арматуры"
        for item in findings
    )


def test_wiring_cost_saving_is_flagged_without_source_evidence() -> None:
    findings = audit_text_claims(
        "Двухпроводная схема обеспечивает экономию на проводке.",
        "Токовый выход: 4…20 мА, двухпроводная схема.",
        "Решаемые задачи",
    )
    assert any(item.category == "Неподтверждённая экономия при монтаже" for item in findings)


def test_precise_display_claim_is_flagged_without_source_evidence() -> None:
    findings = audit_text_claims(
        "Прибор обеспечивает точное отображение значений давления.",
        "Манометр DM 02. Диапазон: 0–1,6 МПа; класс точности: 1,5.",
        "Тезисы для менеджера",
    )
    assert any(item.category == "Неподтверждённые преимущества" for item in findings)
