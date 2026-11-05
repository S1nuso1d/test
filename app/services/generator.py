from pydantic import ValidationError

from app.config import Settings
from app.schemas import (
    GenerationResponse,
    LLMProductCopy,
    ProductInput,
    SalesSection,
)
from app.services.guardrails import (
    all_generated_text,
    build_characteristics,
    build_source_text,
    find_missing_data,
    find_missing_fields,
    has_substantive_product_data,
    validate_generated_copy,
)
from app.services.llm_client import LLMClient
from app.services.prompts import SYSTEM_PROMPT, build_user_prompt


class GenerationError(RuntimeError):
    """Raised for provider and transport errors; content issues are returned as review drafts."""


def _format_commercial_block(sales: SalesSection) -> str:
    parts = ["Кому подходит:"]
    parts.extend(f"• {item}" for item in sales.suitable_for)
    parts.append("Решаемые задачи:")
    parts.extend(f"• {item}" for item in sales.tasks_solved)
    if sales.pitch.strip():
        parts.extend(["Тезисы для менеджера:", sales.pitch.strip()])
    return "\n".join(parts)


def _validation_feedback(issues: list[str], attempt: int) -> str:
    return (
        f"Попытка {attempt} из 3 не прошла локальную проверку. Исправь перечисленные ошибки. "
        "Проверь длину текста самостоятельно; не заполняй объём повторениями и не добавляй "
        "неподтверждённые характеристики. Если исходных фактов недостаточно для честного "
        "описания, прямо скажи об этом, даже если текст не достигнет требуемой длины.\n- "
        + "\n- ".join(issues)
    )


def _to_response(
    product: ProductInput,
    raw: LLMProductCopy,
    missing_data,
    issues: list[str],
    attempts: int,
) -> GenerationResponse:
    needs_review = bool(issues)
    warnings = ["Черновик требует проверки контент-менеджером перед публикацией."]
    if missing_data.fields or missing_data.empty_specs or missing_data.expected_specs:
        warnings.append(
            "В исходных данных отсутствуют некоторые поля или ожидаемые характеристики; "
            "проверьте, применимы ли они к этой модели, и запросите недостающие сведения."
        )
    if needs_review:
        warnings.append(
            "После трёх попыток остались нарушения формальных требований. Карточка сохранена "
            "как черновик для ручной проверки и не должна считаться готовой к публикации."
        )

    sales = raw.sales_section
    return GenerationResponse(
        status="needs_review" if needs_review else "generated",
        product_name=product.name,
        manufacturer=product.manufacturer,
        seo_title=raw.seo_title.strip(),
        seo_description=raw.seo_description.strip(),
        key_characteristics=build_characteristics(product, missing_data),
        seo_queries=[item.strip() for item in raw.seo_queries if item and item.strip()],
        sales_section=sales,
        commercial_block=_format_commercial_block(sales),
        missing_fields=find_missing_fields(product),
        missing_data=missing_data,
        warnings=warnings,
        validation_errors=issues,
        attempts=attempts,
    )


async def generate_product_copy(
    product: ProductInput,
    settings: Settings,
) -> GenerationResponse:
    missing_data = find_missing_data(product)
    if not has_substantive_product_data(product):
        return GenerationResponse(
            status="needs_data",
            product_name=product.name,
            manufacturer=product.manufacturer,
            key_characteristics=build_characteristics(product, missing_data),
            missing_fields=find_missing_fields(product),
            missing_data=missing_data,
            warnings=[
                "Недостаточно исходной информации. Укажите название товара и хотя бы одно "
                "содержательное описание или техническую характеристику."
            ],
            attempts=0,
        )

    client = LLMClient(settings)
    source_text = build_source_text(product)
    correction: str | None = None
    best_draft: LLMProductCopy | None = None
    best_issues: list[str] = []
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        raw_result = await client.generate_json(
            SYSTEM_PROMPT,
            build_user_prompt(product, correction=correction),
        )
        try:
            draft = LLMProductCopy.model_validate(raw_result)
        except ValidationError as exc:
            issues = [
                f"Ошибка структуры ответа: {'.'.join(map(str, item['loc']))}: {item['msg']}"
                for item in exc.errors(include_url=False)[:5]
            ]
            if attempt == max_attempts:
                # If required structure is missing, do not fabricate a response object.
                raise GenerationError(
                    f"Ollama {max_attempts} раза вернул некорректную структуру: " + "; ".join(issues)
                ) from exc
            correction = _validation_feedback(issues, attempt)
            continue

        issues = validate_generated_copy(draft, source_text)
        best_draft, best_issues = draft, issues
        if not issues:
            return _to_response(product, draft, missing_data, [], attempt)
        correction = _validation_feedback(issues, attempt)

    assert best_draft is not None
    return _to_response(product, best_draft, missing_data, best_issues, max_attempts)
