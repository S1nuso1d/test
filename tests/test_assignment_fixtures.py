import json
from pathlib import Path

import pytest

from app.schemas import ProductInput

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("filename", "category", "name_fragment"),
    [
        (
            "product_oven_dts024_100p_v3_30_1.json",
            "temperature_sensor",
            "ДТС024-100П.В3.30/1",
        ),
        (
            "product_oven_pd100_di4_0_185_0_5.json",
            "pressure_transmitter",
            "ПД100-ДИ4,0-185-0,5",
        ),
    ],
)
def test_selected_supplier_product_fixtures_validate(
    filename: str,
    category: str,
    name_fragment: str,
) -> None:
    fixture_path = ROOT / "examples" / filename
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    product = ProductInput.model_validate(payload)

    assert product.category == category
    assert name_fragment in (product.name or "")
    assert len(product.specs) >= 10
    assert product.description


def test_pd100_fixture_does_not_claim_conflicting_source_values() -> None:
    fixture_path = ROOT / "examples" / "product_oven_pd100_di4_0_185_0_5.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert "Тип присоединения" not in payload["specs"]
    assert "Сопротивление нагрузки" not in payload["specs"]


def test_dts024_fixture_does_not_choose_an_unspecified_accuracy_class() -> None:
    fixture_path = ROOT / "examples" / "product_oven_dts024_100p_v3_30_1.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert "Класс допуска" not in payload["specs"]
