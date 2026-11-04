from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductInput(BaseModel):
    """Input product data. Incomplete records are accepted and reported to the user."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = None
    manufacturer: str | None = None
    specs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    description: str | None = None

    @field_validator("name", "manufacturer", "description", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Ожидается текстовое значение")
        cleaned = value.strip()
        return cleaned or None

    @field_validator("specs", mode="before")
    @classmethod
    def normalize_specs(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("Поле specs должно быть JSON-объектом")

        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            if isinstance(raw_value, str):
                raw_value = raw_value.strip() or None
            normalized[key] = raw_value
        return normalized


class KeyCharacteristic(BaseModel):
    name: str
    value: str


class ProductCopy(BaseModel):
    seo_title: str = Field(min_length=1, max_length=70)
    seo_description: str = Field(min_length=800, max_length=1200)
    seo_queries: list[str] = Field(min_length=3, max_length=5)
    commercial_block: str = Field(min_length=1, max_length=1500)

    @field_validator("seo_title", "seo_description", "commercial_block")
    @classmethod
    def strip_generated_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("seo_queries")
    @classmethod
    def validate_queries(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not 3 <= len(cleaned) <= 5:
            raise ValueError("Нужно сформировать от 3 до 5 поисковых запросов")
        return cleaned


class LLMProductCopy(BaseModel):
    """JSON schema sent to Ollama for constrained output.

    Length and item-count constraints are checked locally by ProductCopy after parsing.
    Keeping this JSON schema to basic types improves model compatibility.
    """

    model_config = ConfigDict(extra="forbid")

    seo_title: str
    seo_description: str
    seo_queries: list[str]
    commercial_block: str


class GenerationResponse(BaseModel):
    status: Literal["generated", "needs_data"]
    seo_title: str | None = None
    seo_description: str | None = None
    key_characteristics: list[KeyCharacteristic] = Field(default_factory=list)
    seo_queries: list[str] = Field(default_factory=list)
    commercial_block: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
