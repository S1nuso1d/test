from app.schemas import ProductInput
from app.services.guardrails import (
    build_characteristics,
    find_missing_fields,
    find_unsupported_numbers,
    has_substantive_product_data,
)


def test_technical_characteristics_are_copied_from_source() -> None:
    product = ProductInput(
        name="Манометр DM 02",
        specs={"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5"},
    )

    result = build_characteristics(product)

    assert [(item.name, item.value) for item in result] == [
        ("диапазон измерений", "0–1,6 МПа"),
        ("класс точности", "1,5"),
    ]


def test_missing_fields_are_reported() -> None:
    product = ProductInput(name="Манометр DM 02")

    assert find_missing_fields(product) == ["manufacturer", "description", "specs"]
    assert has_substantive_product_data(product) is False


def test_empty_input_is_accepted_but_marked_as_insufficient() -> None:
    product = ProductInput(name="  ", manufacturer="", description="", specs={})

    assert product.name is None
    assert has_substantive_product_data(product) is False
    assert "name" in find_missing_fields(product)


def test_numeric_guard_catches_numbers_not_in_source() -> None:
    unsupported = find_unsupported_numbers(
        "Диапазон составляет 0–1,6 МПа, корпус имеет диаметр 150 мм.",
        "Диапазон измерений: 0–1,6 МПа; диаметр корпуса: 100 мм",
    )

    assert unsupported == ["150"]


def test_numeric_guard_accepts_source_numbers() -> None:
    unsupported = find_unsupported_numbers(
        "Класс точности — 1.5, диаметр корпуса — 100 мм.",
        "Класс точности: 1,5; диаметр корпуса: 100 мм",
    )

    assert unsupported == []
