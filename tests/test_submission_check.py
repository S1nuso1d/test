from scripts.run_submission_check import evaluate_result


def make_product():
    return {
        "name": "Манометр DM 02",
        "manufacturer": "Манотомь",
        "specs": {
            "диапазон измерений": "0–1,6 МПа",
            "класс точности": "1,5",
        },
    }


def make_result():
    return {
        "status": "generated",
        "seo_title": "Манометр DM 02 Манотомь",
        "seo_description": "x" * 950,
        "seo_queries": [
            "манометр DM 02",
            "манометр Манотомь",
            "манометр 0–1,6 МПа",
        ],
        "key_characteristics": [
            {"name": "диапазон измерений", "value": "0–1,6 МПа"},
            {"name": "класс точности", "value": "1,5"},
        ],
        "sales_section": {
            "suitable_for": ["Специалисты по КИПиА"],
            "tasks_solved": ["Измерение избыточного давления"],
            "pitch": "Проверьте параметры по паспорту перед подбором.",
        },
        "fact_check_findings": [],
        "validation_errors": [],
        "seo_fallback_used": False,
    }


def test_evaluate_result_accepts_complete_card():
    assert evaluate_result(make_product(), make_result()) == []


def test_evaluate_result_rejects_short_seo_description():
    result = make_result()
    result["seo_description"] = "Короткое описание"
    assert any(
        "800–1200" in item
        for item in evaluate_result(make_product(), result)
    )


def test_evaluate_result_rejects_missing_source_characteristic():
    result = make_result()
    result["key_characteristics"].pop(0)
    issues = evaluate_result(make_product(), result)
    assert any("0–1,6 МПа" in item for item in issues)


def test_evaluate_result_rejects_fallback_and_unverified_claims():
    result = make_result()
    result["seo_fallback_used"] = True
    result["fact_check_findings"] = [{"claim": "пылевлагозащита IP65"}]
    issues = evaluate_result(make_product(), result)
    assert any("резервный SEO-шаблон" in item for item in issues)
    assert any("неподтверждённые утверждения" in item for item in issues)


def test_evaluate_result_rejects_technical_phrase_in_audience():
    result = make_result()
    result["sales_section"]["suitable_for"] = ["Покупатели до 1,6 МПа"]
    assert any(
        "Кому подходит" in item
        for item in evaluate_result(make_product(), result)
    )
