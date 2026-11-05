from pydantic import ValidationError

from app.config import Settings
from app.services.claim_audit import audit_draft_claims
from app.schemas import (
    GenerationResponse,
    LLMProductCopy,
    ProductInput,
    SalesSection,
)
from app.services.guardrails import (
    build_characteristics,
    build_safe_seo_description,
    build_source_text,
    calculate_quality_score,
    find_missing_data,
    find_missing_fields,
    has_substantive_product_data,
    validate_generated_copy,
    validate_seo_description,
)
from app.services.llm_client import LLMClient, LLMClientError
from app.services.prompts import (
    SEO_REPAIR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_seo_repair_prompt,
    build_user_prompt,
)


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
        "неподтверждённые характеристики. Если исходных фактов мало, используй нейтральные "
        "рекомендации покупателю по проверке параметров и документов, не описывая их как свойства "
        "товара.\n- "
        + "\n- ".join(issues)
    )


def _to_response(
    product: ProductInput,
    raw: LLMProductCopy,
    missing_data,
    issues: list[str],
    attempts: int,
    seo_repair_attempts: int = 0,
    fallback_used: bool = False,
) -> GenerationResponse:
    source_text = build_source_text(product)
    fact_check_findings = audit_draft_claims(raw, source_text, product)
    needs_review = bool(issues) or fallback_used or bool(fact_check_findings)
    warnings = ["Черновик требует проверки контент-менеджером перед публикацией."]
    if missing_data.fields or missing_data.empty_specs or missing_data.expected_specs:
        warnings.append(
            "В исходных данных отсутствуют некоторые поля или ожидаемые характеристики; "
            "проверьте, применимы ли они к этой модели, и запросите недостающие сведения."
        )
    if fallback_used:
        warnings.append(
            "SEO-описание сформировано резервным локальным шаблоном из исходных данных "
            "и общих рекомендаций по проверке перед покупкой; это не полноценный SEO-текст модели."
            " Обязательно отредактируйте его перед публикацией."
        )
    if issues:
        warnings.append(
            "После повторных попыток остались нарушения формальных требований. Карточка сохранена "
            "как черновик для ручной проверки и не должна считаться готовой к публикации."
        )
    elif fallback_used:
        warnings.append(
            "Модель не смогла подготовить корректное SEO-описание; вместо него подставлен "
            "резервный шаблон. Остальные поля также требуют редакторской проверки."
        )

    sales = raw.sales_section
    if fact_check_findings:
        warnings.append(
            f"Автоматическая проверка обнаружила {len(fact_check_findings)} утверждений, "
            "которые не найдены во входных данных. Проверьте их по паспорту или удалите."
        )
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
        fact_check_findings=fact_check_findings,
        attempts=attempts,
        seo_repair_attempts=seo_repair_attempts,
        quality_score=calculate_quality_score(raw, source_text, product),
        seo_fallback_used=fallback_used,
    )


async def generate_product_copy(
    product: ProductInput,
    settings: Settings,
    model_name: str | None = None,
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
            quality_score=0,
        )

    client = LLMClient(settings, model_name=model_name)
    source_text = build_source_text(product)
    correction: str | None = None
    best_draft: LLMProductCopy | None = None
    best_issues: list[str] = []
    max_attempts = 3

    # First, keep the full-card correction loop. It handles schema, title, query and sales errors.
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
                raise GenerationError(
                    f"Ollama {max_attempts} раза вернул некорректную структуру: " + "; ".join(issues)
                ) from exc
            correction = _validation_feedback(issues, attempt)
            continue

        issues = validate_generated_copy(draft, source_text, product)
        best_draft, best_issues = draft, issues
        if not issues:
            return _to_response(product, draft, missing_data, [], attempt)
        correction = _validation_feedback(issues, attempt)

    if best_draft is None:
        raise GenerationError("Ollama не вернул ни одного структурно корректного черновика.")

    # If the only remaining field-level problem is SEO length/content, repair that field alone.
    seo_issues = validate_seo_description(best_draft.seo_description, source_text, product)
    seo_repair_attempts = 0
    fallback_used = False
    if seo_issues:
        repair_feedback = seo_issues
        for _ in range(1, 3):
            try:
                repaired_description = await client.repair_seo_description(
                    SEO_REPAIR_SYSTEM_PROMPT,
                    build_seo_repair_prompt(
                        product,
                        best_draft.seo_description,
                        repair_feedback,
                    ),
                )
                seo_repair_attempts += 1
            except LLMClientError:
                # A failed focused call must not discard the usable draft; try the deterministic fallback.
                break

            candidate = best_draft.model_copy(
                update={"seo_description": repaired_description}
            )
            repair_feedback = validate_seo_description(candidate.seo_description, source_text, product)
            best_draft = candidate
            if not repair_feedback:
                break

        if validate_seo_description(best_draft.seo_description, source_text):
            try:
                fallback_description = build_safe_seo_description(product)
                fallback_issues = validate_seo_description(fallback_description, source_text, product)
                if not fallback_issues:
                    best_draft = best_draft.model_copy(
                        update={"seo_description": fallback_description}
                    )
                    fallback_used = True
            except ValueError:
                # Keep the best LLM draft and return it as needs_review below.
                pass

        best_issues = validate_generated_copy(best_draft, source_text, product)

    if not best_issues:
        return _to_response(
            product,
            best_draft,
            missing_data,
            [],
            max_attempts,
            seo_repair_attempts=seo_repair_attempts,
            fallback_used=fallback_used,
        )

    return _to_response(
        product,
        best_draft,
        missing_data,
        best_issues,
        max_attempts,
        seo_repair_attempts=seo_repair_attempts,
        fallback_used=fallback_used,
    )
