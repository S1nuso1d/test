import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProductInput(BaseModel):
    """Input product data. Incomplete records are accepted and reported to the user."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    specs: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=60)
    description: str | None = Field(default=None, max_length=12_000)

    @field_validator("name", "manufacturer", "category", "description", mode="before")
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
            if len(key) > 100:
                raise ValueError("Название характеристики не должно превышать 100 символов")
            if isinstance(raw_value, str):
                raw_value = raw_value.strip() or None
                if raw_value is not None and len(raw_value) > 1_000:
                    raise ValueError(f"Значение характеристики «{key}» превышает 1000 символов")
            normalized[key] = raw_value
        return normalized

    @model_validator(mode="after")
    def validate_total_input_size(self) -> "ProductInput":
        total = sum(len(value or "") for value in (self.name, self.manufacturer, self.category, self.description))
        total += sum(len(key) + len(str(value or "")) for key, value in self.specs.items())
        if total > 20_000:
            raise ValueError("Объём исходных данных превышает 20 000 символов")
        return self


class KeyCharacteristic(BaseModel):
    name: str
    value: str


class MissingDataReport(BaseModel):
    category: str
    category_source: Literal["provided", "detected", "generic"]
    fields: list[str] = Field(default_factory=list)
    empty_specs: list[str] = Field(default_factory=list)
    expected_specs: list[str] = Field(default_factory=list)


class SalesSection(BaseModel):
    suitable_for: list[str] = Field(default_factory=list)
    tasks_solved: list[str] = Field(default_factory=list)
    pitch: str = ""


class SEODescriptionOutput(BaseModel):
    """Structured response for a focused SEO-description repair."""

    model_config = ConfigDict(extra="forbid")

    seo_description: str


class LLMProductCopy(BaseModel):
    """Structured response requested from Ollama; strict lengths are checked locally."""

    model_config = ConfigDict(extra="forbid")

    seo_title: str
    seo_description: str
    seo_queries: list[str]
    sales_section: SalesSection


class GenerationResponse(BaseModel):
    status: Literal["generated", "needs_data", "needs_review"]
    product_name: str | None = None
    manufacturer: str | None = None
    seo_title: str | None = None
    seo_description: str | None = None
    key_characteristics: list[KeyCharacteristic] = Field(default_factory=list)
    seo_queries: list[str] = Field(default_factory=list)
    sales_section: SalesSection | None = None
    commercial_block: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    missing_data: MissingDataReport | None = None
    warnings: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    attempts: int = 0
    seo_repair_attempts: int = Field(default=0, ge=0, le=2)
    quality_score: int | None = Field(default=None, ge=0, le=100)
    seo_fallback_used: bool = False


class BatchGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    products: list[ProductInput] = Field(min_length=1, max_length=10)


class ModelBenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: ProductInput
    models: list[str] = Field(min_length=2, max_length=3)

    @field_validator("models")
    @classmethod
    def validate_model_names(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(
            not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", name)
            for name in normalized
        ):
            raise ValueError("Укажите корректные имена моделей Ollama")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Для сравнения выберите разные модели")
        return normalized


class ModelBenchmarkItem(BaseModel):
    model: str
    elapsed_seconds: float = Field(ge=0)
    result: GenerationResponse | None = None
    error: str | None = None


class ModelBenchmarkResponse(BaseModel):
    total: int
    completed: int
    failed: int
    items: list[ModelBenchmarkItem]


class BatchGenerationItem(BaseModel):
    index: int
    product_name: str | None = None
    result: GenerationResponse | None = None
    error: str | None = None


class BatchGenerationResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    items: list[BatchGenerationItem]
