import pytest
from pydantic import ValidationError

from app.schemas import ProductInput


def test_product_input_rejects_more_than_sixty_characteristics() -> None:
    specs = {f"Параметр {index}": f"Значение {index}" for index in range(61)}
    with pytest.raises(ValidationError):
        ProductInput(name="Тестовый прибор", specs=specs)


def test_product_input_rejects_oversized_characteristic_value() -> None:
    with pytest.raises(ValidationError, match="превышает 1000 символов"):
        ProductInput(name="Тестовый прибор", specs={"Описание параметра": "x" * 1001})


def test_product_input_rejects_oversized_total_payload() -> None:
    specs = {f"Параметр {index}": "x" * 1000 for index in range(9)}
    with pytest.raises(ValidationError, match="20 000 символов"):
        ProductInput(name="Тестовый прибор", description="x" * 12_000, specs=specs)
