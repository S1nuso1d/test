from app.schemas import LLMProductCopy
from app.services.claim_audit import audit_draft_claims, audit_text_claims


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
