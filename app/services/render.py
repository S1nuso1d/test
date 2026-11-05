from app.schemas import GenerationResponse


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def to_markdown(result: GenerationResponse) -> str:
    title = result.product_name or "Товар без названия"
    lines = [f"# {title} — черновик карточки товара", ""]
    lines += ["## SEO-заголовок", result.seo_title or "Не сформирован", ""]
    description = result.seo_description or "Не сформировано"
    lines += [f"## SEO-описание ({len(result.seo_description or '')} символов)", description, ""]
    lines += ["## Ключевые характеристики", "", "| Параметр | Значение |", "|---|---|"]
    lines += [f"| {_escape_cell(item.name)} | {_escape_cell(item.value)} |" for item in result.key_characteristics]
    lines += ["", "## Поисковые запросы"]
    lines += [f"- {query}" for query in result.seo_queries] or ["- Не сформированы"]
    lines += ["", "## Коммерческий блок", result.commercial_block or "Не сформирован", ""]
    lines += ["## Недостающие сведения"]
    if result.missing_data:
        missing = result.missing_data
        entries = (
            [f"Поле не заполнено: {field}" for field in missing.fields]
            + [f"Пустая характеристика: {field}" for field in missing.empty_specs]
            + [f"Ожидаемая характеристика отсутствует: {field}" for field in missing.expected_specs]
        )
    else:
        entries = result.missing_fields
    lines += [f"- {entry}" for entry in entries] or ["- Не обнаружены"]
    lines += [
        "",
        "## Статус и предупреждения",
        f"Статус: **{result.status}**",
        f"Попыток полной генерации: {result.attempts}",
        f"Попыток целевого исправления SEO: {result.seo_repair_attempts}",
    ]
    if result.quality_score is not None:
        lines.append(
            f"Формальная оценка: {result.quality_score}/100 "
            "(проверяет формат и числовые значения, но не доказывает фактическую достоверность)"
        )
    lines += [f"- {warning}" for warning in result.warnings]
    if result.validation_errors:
        lines += ["", "## Ошибки проверки"]
        lines += [f"- {issue}" for issue in result.validation_errors]
    return "\n".join(lines) + "\n"
