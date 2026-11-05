import re
from collections.abc import Iterable

from app.schemas import FactCheckFinding, LLMProductCopy


# These rules target concrete product properties or formal statuses that are
# costly to invent. They are intentionally conservative and lexical: a match
# is a review signal, not proof that every other sentence is factually correct.
_RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "Материал корпуса: нержавеющая сталь",
        r"нержавеющ\w*\s+стал\w*|нержавейк\w*",
        "warning",
        "Во входных данных не найдено подтверждение материала корпуса.",
    ),
    (
        "Материал: латунь",
        r"латунн\w*",
        "warning",
        "Во входных данных не найдено подтверждение использования латуни.",
    ),
    (
        "Материал: алюминий",
        r"алюминиев\w*",
        "warning",
        "Во входных данных не найдено подтверждение использования алюминия.",
    ),
    (
        "Материал корпуса: пластик",
        r"пластиков\w*\s+корпус|корпус\w*\s+из\s+пластик\w*",
        "warning",
        "Во входных данных не найдено подтверждение пластикового корпуса.",
    ),
    (
        "Степень защиты IP",
        r"\bIP\s*[- ]?\d{2,3}\b",
        "warning",
        "Степень защиты IP не указана в исходных данных.",
    ),
    (
        "Влагозащита",
        r"влагозащит\w*|водонепроницаем\w*|пылевлагозащит\w*",
        "warning",
        "Влагозащита или водонепроницаемость не подтверждена исходными данными.",
    ),
    (
        "Взрывозащита",
        r"взрывозащит\w*|взрывобезопас\w*|искробезопас\w*|\bEx\s*[dibe]\b",
        "critical",
        "Взрывозащита — критически важное свойство; требуется прямое подтверждение в паспорте.",
    ),
    (
        "Сертификация или допуск",
        r"сертификат\w*|сертифицир\w*|декларац\w+\s+соответств\w*|"
        r"гос(?:ударственн\w+\s+)?реестр\w*|утвержден\w+\s+тип\w*",
        "critical",
        "Сертификат, допуск или регистрационный статус не подтверждён исходными данными.",
    ),
    (
        "Поверка или метрологический статус",
        r"поверк\w*|межповерочн\w*|метрологическ\w*",
        "warning",
        "Сведения о поверке и метрологическом статусе отсутствуют во входных данных.",
    ),
    (
        "Беспроводная связь",
        r"беспроводн\w*|\bbluetooth\b|\bwi[ -]?fi\b",
        "warning",
        "Наличие беспроводной связи не подтверждено исходными данными.",
    ),
    (
        "Дисплей или индикация",
        r"диспле\w*|экран\w*|подсвет\w*|цифров\w+\s+индикац\w*",
        "warning",
        "Наличие дисплея, экрана или подсветки не подтверждено исходными данными.",
    ),
    (
        "Пищевая или санитарная совместимость",
        r"пищев\w*\s+промышленност\w*|санитарн\w*\s+исполнен\w*|"
        r"гигиеническ\w*\s+исполнен\w*|\bFDA\b|\b3-A\b",
        "warning",
        "Пищевая или санитарная совместимость не подтверждена исходными данными.",
    ),
    (
        "Стойкость к агрессивной среде",
        r"коррозионностойк\w*|кислотостойк\w*|для\s+агрессивн\w*\s+сред\w*",
        "warning",
        "Стойкость к коррозии или агрессивной среде не подтверждена исходными данными.",
    ),
    (
        "Гарантия",
        r"гаранти\w*(?:\s+\w+){0,2}",
        "warning",
        "Условия гарантии не указаны во входных данных.",
    ),
)


def audit_text_claims(
    generated_text: str,
    source_text: str,
    field: str,
) -> list[FactCheckFinding]:
    """Flag selected high-impact product claims absent from the supplied input.

    This is a deterministic phrase audit, not an LLM fact verifier. It only
    checks the explicit rule set above and must not be presented as proof that
    text without findings is factually correct.
    """
    source = source_text.casefold()
    findings: list[FactCheckFinding] = []
    seen: set[tuple[str, str]] = set()

    for label, expression, severity, explanation in _RULES:
        pattern = re.compile(expression, re.IGNORECASE)
        if pattern.search(source):
            continue

        for match in pattern.finditer(generated_text):
            claim = match.group(0).strip()
            key = (label, claim.casefold())
            if key in seen:
                continue

            # Do not flag a disclaimer or a buyer checklist as a positive product claim.
            context = generated_text[
                max(0, match.start() - 55) : min(len(generated_text), match.end() + 55)
            ].casefold()
            if re.search(
                r"не указано|не указана|не подтвержден|не подтверждена|отсутствует|нет данных|"
                r"уточните|проверьте|сверьте|запросите|подтвердите|не позволяет|"
                r"нельзя подтвердить|нельзя делать вывод|не заменяет|следует проверить|"
                r"может потребоваться|не переносите выводы",
                context,
            ):
                continue

            seen.add(key)
            findings.append(
                FactCheckFinding(
                    field=field,
                    category=label,
                    claim=claim[:120],
                    severity=severity,
                    message=explanation,
                )
            )
            break

    return findings


def audit_draft_claims(
    draft: LLMProductCopy,
    source_text: str,
) -> list[FactCheckFinding]:
    """Audit every generated text field against the original product input."""
    sales = draft.sales_section
    fields: Iterable[tuple[str, str]] = (
        ("SEO-заголовок", draft.seo_title),
        ("SEO-описание", draft.seo_description),
        ("Поисковые запросы", "\n".join(draft.seo_queries)),
        ("Кому подходит", "\n".join(sales.suitable_for)),
        ("Решаемые задачи", "\n".join(sales.tasks_solved)),
        ("Тезисы для менеджера", sales.pitch),
    )

    findings: list[FactCheckFinding] = []
    for field, content in fields:
        findings.extend(audit_text_claims(content, source_text, field))
    return findings
