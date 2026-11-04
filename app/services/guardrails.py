import re
from typing import Any

from app.schemas import KeyCharacteristic, ProductInput

_NUMBER_PATTERN = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?(?![\w])")


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def build_source_text(product: ProductInput) -> str:
    parts = [product.name or "", product.manufacturer or "", product.description or ""]
    parts.extend(f"{key}: {_stringify(value)}" for key, value in product.specs.items())
    return "\n".join(part for part in parts if part)


def build_characteristics(product: ProductInput) -> list[KeyCharacteristic]:
    """Copy supplied technical values verbatim; never ask the LLM to invent this section."""
    characteristics = [
        KeyCharacteristic(name=key, value=_stringify(value) or "данных нет")
        for key, value in product.specs.items()
    ]
    if not characteristics:
        characteristics.append(
            KeyCharacteristic(name="Технические характеристики", value="данных нет")
        )
    return characteristics


def find_unsupported_numbers(generated_text: str, source_text: str) -> list[str]:
    """Catch new numeric values in generated copy that are absent from source data.

    This is a lightweight safety check, not a full semantic fact-checker.
    """
    source_numbers = {
        token.replace(",", ".") for token in _NUMBER_PATTERN.findall(source_text)
    }
    generated_numbers = {
        token.replace(",", ".") for token in _NUMBER_PATTERN.findall(generated_text)
    }
    return sorted(generated_numbers - source_numbers)


def find_missing_fields(product: ProductInput) -> list[str]:
    missing: list[str] = []
    if not product.name:
        missing.append("name")
    if not product.manufacturer:
        missing.append("manufacturer")
    if not product.description:
        missing.append("description")
    if not any(value is not None and str(value).strip() for value in product.specs.values()):
        missing.append("specs")
    return missing


def has_substantive_product_data(product: ProductInput) -> bool:
    has_specs = any(value is not None and str(value).strip() for value in product.specs.values())
    return bool(product.name and (product.description or has_specs))
