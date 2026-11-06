import re
from collections.abc import Iterable

from app.schemas import FactCheckFinding, LLMProductCopy, ProductInput


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
        r"взрывозащищ\w*|взрывобезопас\w*|искробезопас\w*|\bEx\s*[dibe]\b",
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
    (
        "Неподтверждённые преимущества",
        r"над[её]жн\w*|высокоточн\w*|долговечн\w*|универсальн\w*|эффективн\w*|удобн\w*",
        "warning",
        "Оценочные преимущества не подтверждены характеристиками или описанием источника.",
    ),
    (
        "Совместимость и интеграция",
        r"совместим\w*|интеграц\w*",
        "warning",
        "Совместимость и возможность интеграции требуют подтверждения для конкретной модификации.",
    ),
    (
        "Условия монтажа",
        r"монтаж\w*|установк\w*|встраив\w*",
        "warning",
        "Способ и условия монтажа должны быть подтверждены документацией конкретной модели.",
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
    findings: list[FactCheckFinding] = []
    seen: set[tuple[str, str]] = set()

    for label, expression, severity, explanation in _RULES:
        pattern = re.compile(expression, re.IGNORECASE)
        source_matches = {
            re.sub(r"\s+", "", match.group(0)).upper()
            for match in pattern.finditer(source_text)
        }

        for match in pattern.finditer(generated_text):
            claim = match.group(0).strip()
            if label == "Степень защиты IP":
                if re.sub(r"\s+", "", claim).upper() in source_matches:
                    continue
            elif source_matches:
                continue
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






# Specific aliases are checked before generic ones. In particular, temperature ranges
# must not be mistaken for measurement ranges merely because both contain "диапазон".
_SPEC_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Диапазон температуры",
        (
            r"(?<!\w)диапазон(?:а|у|ом|е)?\s+температур\w*(?!\w)",
            r"(?<!\w)температур\w*\s+диапазон(?:а|у|ом|е)?(?!\w)",
        ),
    ),
    (
        "Диапазон расхода",
        (
            r"(?<!\w)диапазон(?:а|у|ом|е)?\s+расход\w*(?!\w)",
            r"(?<!\w)предел(?:а|у|ом|е)?\s+расход\w*(?!\w)",
            r"(?<!\w)расход\w*\s+(?:в\s+)?диапазон\w*(?!\w)",
            r"(?<!\w)flow\s+range(?!\w)",
        ),
    ),
    (
        "Диапазон измерений",
        (
            r"(?<!\w)диапазон(?:а|у|ом|е)?\s+измерени\w*(?!\w)",
            r"(?<!\w)предел(?:а|у|ом|е)?\s+измерени\w*(?!\w)",
            r"(?<!\w)measurement\s+range(?!\w)",
        ),
    ),
    (
        "Диапазон",
        (
            r"(?<!\w)диапазон(?:а|у|ом|е)?(?!\w)",
            r"(?<!\w)range(?!\w)",
        ),
    ),
    (
        "Класс точности",
        (
            r"(?<!\w)класс(?:а|у|ом|е)?\s+точност\w*(?!\w)",
            r"(?<!\w)точност\w*(?!\w)",
            r"(?<!\w)accuracy\s+class(?!\w)",
            r"(?<!\w)accuracy(?!\w)",
        ),
    ),
    (
        "Присоединение",
        (
            r"(?<!\w)присоединени\w*(?!\w)",
            r"(?<!\w)резьб\w*(?!\w)",
            r"(?<!\w)тип\s+соединени\w*(?!\w)",
            r"(?<!\w)connection(?!\w)",
            r"(?<!\w)thread(?!\w)",
        ),
    ),
    (
        "Диаметр корпуса",
        (
            r"(?<!\w)диаметр\w*(?:\s+(?:корпус\w*|циферблат\w*))?(?!\w)",
            r"(?<!\w)case\s+diameter(?!\w)",
            r"(?<!\w)dial\s+diameter(?!\w)",
            r"(?<!\w)diameter(?!\w)",
        ),
    ),
    (
        "Степень защиты",
        (
            r"(?<!\w)степен\w*\s+защит\w*(?!\w)",
            r"(?<!\w)защит\w*\s+ip(?!\w)",
            r"(?<!\w)ip(?!\w)",
            r"(?<!\w)ingress\s+protection(?!\w)",
        ),
    ),
    (
        "Напряжение питания",
        (
            r"(?<!\w)напряжени\w*(?:\s+питани\w*)?(?!\w)",
            r"(?<!\w)питани\w*(?!\w)",
            r"(?<!\w)supply\s+voltage(?!\w)",
            r"(?<!\w)power\s+supply(?!\w)",
        ),
    ),
    (
        "Выходной сигнал",
        (
            r"(?<!\w)выходн\w*\s+сигнал\w*(?!\w)",
            r"(?<!\w)сигнал\w*\s+выход\w*(?!\w)",
            r"(?<!\w)output\s+signal(?!\w)",
            r"(?<!\w)output(?!\w)",
        ),
    ),
)
_SPEC_NUMBER_RE = re.compile(r"(?<![\w])[-−+]?\d+(?:[.,]\d+)?(?![\w])")
_SPEC_UNIT_RE = re.compile(
    r"(?<![\w])(?P<number>[-−+]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>°\s*[cсfф]|м³/ч|м3/ч|л/мин|л/ч|мпа|кпа|гпа|па|бар|атм|"
    r"мм|см|мкм|нм|км|м|ма|квт|вт|мв|кв|кг|мг|г|мл|л|(?-i:В|А)|"
    r"khz|mhz|ghz|hz|mpa|kpa|gpa|pa|bar|atm|mm|cm|um|nm|km|"
    r"ma|kw|w|mv|kv|(?-i:V|A)|kg|mg|g|ml|l)"
    r"(?![\w])",
    re.IGNORECASE,
)


def _normalized_numbers(text: str) -> set[str]:
    return {
        format(float(value.replace(",", ".").replace("−", "-")), ".12g")
        for value in _SPEC_NUMBER_RE.findall(text)
    }


def _normalized_pairs(text: str) -> set[tuple[str, str]]:
    return {
        (
            format(float(match.group("number").replace(",", ".").replace("−", "-")), ".12g"),
            re.sub(r"\s+", "", match.group("unit").casefold()),
        )
        for match in _SPEC_UNIT_RE.finditer(text)
    }


def _aliases_for_spec(key: str) -> tuple[re.Pattern[str], ...]:
    """Return whole-word patterns for a known characteristic, including inflections."""
    for _label, expressions in _SPEC_ALIAS_GROUPS:
        patterns = tuple(re.compile(expression, re.IGNORECASE) for expression in expressions)
        if any(pattern.search(key) for pattern in patterns):
            return patterns

    normalized = key.casefold().strip()
    if len(normalized) < 3:
        return ()
    return (re.compile(rf"(?<!\w){re.escape(normalized)}(?!\w)", re.IGNORECASE),)


def find_spec_labels(text: str, product: ProductInput) -> list[str]:
    """Return supplied technical-field names explicitly mentioned in a text fragment."""
    labels: list[str] = []
    for key, raw_value in product.specs.items():
        if raw_value is None or not str(raw_value).strip():
            continue
        if any(pattern.search(text) for pattern in _aliases_for_spec(key)):
            labels.append(key)
    return labels


def _value_context(text: str, match: re.Match[str]) -> str:
    """Keep the complete matched attribute name in the diagnostic context."""
    tail = text[match.end() : match.end() + 180]
    stop = re.search(r"[.!?]\s+|[\n;]", tail)
    value = tail[: stop.start()] if stop else tail
    return (match.group(0) + value).strip()[:120]


def audit_spec_value_mismatches(
    generated_text: str,
    product: ProductInput,
    field: str,
    *,
    allow_missing_units: bool = False,
) -> list[FactCheckFinding]:
    """Check values near known attribute labels against the corresponding source spec."""
    findings: list[FactCheckFinding] = []

    for key, raw_value in product.specs.items():
        if raw_value is None or not str(raw_value).strip():
            continue
        aliases = _aliases_for_spec(key)
        expected_text = str(raw_value)
        expected_numbers = _normalized_numbers(expected_text)
        expected_pairs = _normalized_pairs(expected_text)
        if not aliases or not expected_numbers:
            continue

        mismatch_context: str | None = None
        for pattern in aliases:
            for match in pattern.finditer(generated_text):
                context = _value_context(generated_text, match)
                actual_numbers = _normalized_numbers(context)
                actual_pairs = _normalized_pairs(context)
                if not actual_numbers:
                    continue
                numbers_match = expected_numbers.issubset(actual_numbers)
                # Search queries may omit units, but an explicitly different unit is rejected.
                units_match = (
                    not expected_pairs
                    or expected_pairs.issubset(actual_pairs)
                    or (allow_missing_units and not actual_pairs)
                )
                if not numbers_match or not units_match:
                    mismatch_context = context
                    break
            if mismatch_context:
                break

        if mismatch_context:
            findings.append(
                FactCheckFinding(
                    field=field,
                    category=key,
                    claim=mismatch_context,
                    severity="critical",
                    message=(
                        f"Значение рядом с параметром «{key}» не совпадает с исходным "
                        f"значением «{expected_text}». Сверьте его с источником."
                    ),
                )
            )
    return findings


def audit_draft_claims(
    draft: LLMProductCopy,
    source_text: str,
    product: ProductInput | None = None,
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
        if product is not None:
            findings.extend(
                audit_spec_value_mismatches(
                    content,
                    product,
                    field,
                    allow_missing_units=field == "Поисковые запросы",
                )
            )
    return findings
