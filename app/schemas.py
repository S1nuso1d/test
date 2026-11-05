from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductInput(BaseModel):
    """Input product data. Incomplete records are accepted and reported to the user."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = None
    manufacturer: str | None = None
    category: str | None = None
    specs: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    description: str | None = None

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
            if isinstance(raw_value, str):
                raw_value = raw_value.strip() or None
            normalized[key] = raw_value
        return normalized


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


class BatchGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    products: list[ProductInput] = Field(min_length=1, max_length=10)


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
