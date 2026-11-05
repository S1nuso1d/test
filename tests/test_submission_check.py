import json
from pathlib import Path

from app.schemas import ProductInput
from scripts.run_submission_check import assignment_examples_confirmed, evaluate_result


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


def test_evaluate_result_requires_missing_data_marker():
    product = make_product()
    result = make_result()
    result["missing_data"] = {"expected_specs": ["Степень защиты"]}
    result["key_characteristics"].append(
        {"name": "Степень защиты", "value": "данных нет"}
    )
    assert evaluate_result(product, result) == []


def test_evaluate_result_rejects_missing_marker_omission():
    product = make_product()
    result = make_result()
    result["missing_data"] = {"expected_specs": ["Степень защиты"]}
    result["key_characteristics"].append(
        {"name": "Степень защиты", "value": "IP65"}
    )
    assert any(
        "данных нет" in issue
        for issue in evaluate_result(product, result)
    )


def test_external_demo_does_not_confirm_employer_assignment_inputs():
    assert not assignment_examples_confirmed(2, 2, employer_data_confirmed=False)


def test_two_employer_inputs_can_confirm_assignment_completeness():
    assert assignment_examples_confirmed(2, 2, employer_data_confirmed=True)


def test_assignment_stays_incomplete_without_two_successful_results():
    assert not assignment_examples_confirmed(2, 1, employer_data_confirmed=True)


def test_external_oven_demo_product_is_valid_input():
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "product_owen_pd100i_external_demo.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    product = ProductInput.model_validate(payload)

    assert product.manufacturer == "ОВЕН"
    assert product.category == "pressure_transmitter"
    assert product.specs["Диапазон измерений"] == "0–1,6 МПа"
    assert product.specs["Присоединение"] == "G1/2 A DIN 3852"
    assert product.specs["Класс точности"].startswith("0,5")
    assert product.specs["Выходной сигнал"].startswith("4–20 мА")


def test_external_oven_demo_has_provenance_warning():
    path = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "product_owen_pd100i_external_demo.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "не был предоставлен работодателем" in payload["description"]
