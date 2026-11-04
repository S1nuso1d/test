from pydantic import ValidationError

from app.config import Settings
from app.schemas import GenerationResponse, ProductCopy, ProductInput
from app.services.guardrails import (
    build_characteristics,
    build_source_text,
    find_missing_fields,
    find_unsupported_numbers,
    has_substantive_product_data,
)
from app.services.llm_client import LLMClient, LLMClientError
from app.services.prompts import SYSTEM_PROMPT, build_user_prompt


class GenerationError(RuntimeError):
    """Raised when safe, schema-compliant product copy cannot be generated."""


async def generate_product_copy(
    product: ProductInput,
    settings: Settings,
) -> GenerationResponse:
    missing_fields = find_missing_fields(product)
    characteristics = build_characteristics(product)

    if not has_substantive_product_data(product):
        return GenerationResponse(
            status="needs_data",
            key_characteristics=characteristics,
            missing_fields=missing_fields,
            warnings=[
                "Недостаточно исходной информации. Укажите название товара и хотя бы "
                "одно содержательное описание или техническую характеристику."
            ],
        )

    client = LLMClient(settings)
    source_text = build_source_text(product)
    correction: str | None = None

    for attempt in range(2):
        raw_result = await client.generate_json(
            SYSTEM_PROMPT,
            build_user_prompt(product, correction=correction),
        )
        try:
            draft = ProductCopy.model_validate(raw_result)
        except ValidationError as exc:
            validation_issues = exc.errors(include_url=False)[:5]
            if attempt == 0:
                correction = (
                    "Ответ не прошёл проверку формата и ограничений полей. "
                    "Исправь только перечисленные проблемы, сохранив фактическую точность: "
                    + str(validation_issues)
                )
                continue
            raise GenerationError(
                "Модель дважды вернула результат, не соответствующий требованиям: "
                + str(validation_issues)
            ) from exc

        text_to_check = f"{draft.seo_description}\n{draft.commercial_block}"
        unsupported_numbers = find_unsupported_numbers(text_to_check, source_text)
        if not unsupported_numbers:
            warnings = [
                "Сгенерированный текст является черновиком и требует проверки контент-менеджером."
            ]
            if missing_fields:
                warnings.append(
                    "Часть сведений отсутствует во входных данных; соответствующие пробелы "
                    "должны быть уточнены до публикации."
                )
            return GenerationResponse(
                status="generated",
                seo_title=draft.seo_title,
                seo_description=draft.seo_description,
                key_characteristics=characteristics,
                seo_queries=draft.seo_queries,
                commercial_block=draft.commercial_block,
                missing_fields=missing_fields,
                warnings=warnings,
            )

        correction = (
            "Числовые значения, которых нет в источнике: " + ", ".join(unsupported_numbers)
        )

    raise GenerationError(
        "Не удалось получить текст без неподтверждённых числовых значений. "
        "Попробуйте уточнить исходные данные или повторить запрос."
    )
