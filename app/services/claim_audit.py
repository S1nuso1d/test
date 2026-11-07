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
        "Повышенная влажность и пыль",
        r"повышенн\w*\s+влажн\w*|высок\w*\s+влажн\w*|"
        r"влажност\w*\s+и\s+пыл\w*|пылевлажн\w*|запыленн\w*",
        "warning",
        "Работа при повышенной влажности или запылённости не подтверждена входными данными.",
    ),
    (
        "Подмена измеряемого давления нагрузкой",
        r"максимальн\w*\s+нагрузк\w*|предельн\w*\s+нагрузк\w*",
        "warning",
        "В характеристиках указано измеряемое давление, а не общая или механическая нагрузка.",
    ),
    (
        "Материал корпуса перепутан с материалом защитной арматуры",
        r"корпус\w*[^.!?\n]{0,60}(?:стал\w*|латун\w*|алюмини\w*)|"
        r"(?:стал\w*|латун\w*|алюмини\w*)[^.!?\n]{0,60}корпус\w*",
        "warning",
        "Материал защитной арматуры нельзя автоматически переносить на корпус прибора.",
    ),
    (
        "Фланцевое присоединение",
        r"фланцев\w*\s+(?:соединени\w*|присоединени\w*|подключени\w*)",
        "warning",
        "Тип присоединения G1/2 сам по себе не подтверждает фланцевое соединение.",
    ),
    (
        "Неподтверждённая экономия при монтаже",
        r"экономи\w*\s+(?:на\s+проводк\w*|за\s+сч[её]т)|"
        r"сниж\w*\s+(?:затрат\w*|стоимост\w*|расход\w*)",
        "warning",
        "Экономия или снижение затрат не подтверждены исходными данными.",
    ),
    (
        "Объект или место установки",
        r"на\s+(?:панел\w*|шкаф\w*)\s+(?:управлен\w*|контрол\w*)|"
        r"(?:в|для)\s+(?:трубопровод\w*|сосуд\w*)",
        "warning",
        "Конкретное место установки или объект применения не подтверждены входными данными.",
    ),
    (
        "Стойкость к агрессивной среде",
        r"коррозионностойк\w*|кислотостойк\w*|агрессивн\w*\s+(?:сред\w*|услови\w*)",
        "warning",
        "Стойкость к коррозии или агрессивной среде не подтверждена исходными данными.",
    ),
    (
        "Тяжёлые условия эксплуатации",
        r"(?:тяжёл\w*|тяжел\w*|жёстк\w*|жестк\w*|сложн\w*|экстремальн\w*)\s+"
        r"(?:услови\w*|режим\w*)(?:\s+эксплуатаци\w*)?|"
        r"устойчив\w*\s+к\s+(?!климатическ)\w+|вибро\w+|ударопрочн\w*",
        "warning",
        "Работа в тяжёлых условиях или устойчивость к воздействиям не подтверждена исходными данными.",
    ),
    (
        "Гарантия",
        r"гаранти\w*",
        "warning",
        "Условия гарантии не указаны во входных данных.",
    ),
    (
        "Неподтверждённые преимущества",
        r"над[её]жн\w*|высокоточн\w*|долговечн\w*|универсальн\w*|эффективн\w*|"
        r"безотказн\w*|износостойк\w*|прочн\w*|качественн\w*|"
        r"стабильн\w*\s+(?:индикаци\w*|показани\w*|работ\w*)|"
        r"точн\w*\s+(?:показани\w*|индикаци\w*|отображени\w*)|широк\w*\s+спектр\w*|"
        r"стандартн\w*\s+визуальн\w*|"
        r"удобн\w*\s+(?:монтаж\w*|подключени\w*|интеграц\w*|эксплуатаци\w*)",
        "warning",
        "Оценочные преимущества не подтверждены характеристиками или описанием источника.",
    ),
    (
        "Совместимость и интеграция",
        r"(?:полностью\s+)?совместим\w*\s+с\b|"
        r"(?:обеспечивает|гарантирует|позволяет|поддерживает)\w*\s+(?:полную\s+)?"
        r"(?:совместимость|интеграци\w*)|(?:позволяет|позволяющ\w*|даёт\s+возможность)\s+"
        r"интегрир\w*|"
        r"(?:прост\w*|удобн\w*|быстр\w*)\s+интеграци\w*|"
        r"(?:готов\w*|предусмотрен\w*)\s+(?:к\s+)?интеграци\w*",
        "warning",
        "Совместимость и возможность интеграции требуют подтверждения для конкретной модификации.",
    ),
    (
        "Условия монтажа",
        r"монтируется|смонтирован\w*|установлен\w*|устанавливается|встраивается|"
        r"монтаж\w*\s+(?:датчик\w*|непосредственн\w*|в\s+процесс)|"
        r"допускает\s+монтаж|предусмотрен\w*\s+монтаж|"
        r"позволя\w*\s+(?:быстр\w*\s+)?установ\w*",
        "warning",
        "Способ и условия монтажа должны быть подтверждены документацией конкретной модели.",
    ),
)


def _stem_key(text: str) -> str:
    """Normalize a matched phrase to word stems, so inflected forms compare equal."""
    words = re.findall(r"\w+", text.casefold().replace("ё", "е"))
    return " ".join(word[:4] for word in words)


# Advertising-style claims are never excused by a nearby "check the passport" phrase.
_NO_DISCLAIMER_SKIP = frozenset(
    {
        "Неподтверждённые преимущества",
        "Стойкость к агрессивной среде",
        "Тяжёлые условия эксплуатации",
    }
)
_EXPLICIT_NEGATION = (
    r"не указано|не указана|не подтвержден|не подтверждена|не подтверждает|"
    r"не подтверждают|отсутствует|нет данных|нельзя подтвердить|не является|не заявлен"
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
        if label == "Степень защиты IP":
            source_matches = {
                re.sub(r"\s+", "", match.group(0)).upper()
                for match in pattern.finditer(source_text)
            }
        else:
            source_matches = {
                _stem_key(match.group(0)) for match in pattern.finditer(source_text)
            }

        for match in pattern.finditer(generated_text):
            claim = match.group(0).strip()
            if label == "Материал корпуса перепутан с материалом защитной арматуры":
                material_match = re.search(
                    r"стал\w*|латун\w*|алюмини\w*", claim, re.IGNORECASE
                )
                source_housing_materials = re.findall(
                    r"(?:материал\w*\s+корпус\w*|корпус\w*)"
                    r"[^.!?\n]{0,60}(?:стал\w*|латун\w*|алюмини\w*)",
                    source_text,
                    re.IGNORECASE,
                )
                if material_match and any(
                    _stem_key(material_match.group(0)) in _stem_key(source_phrase)
                    for source_phrase in source_housing_materials
                ):
                    continue
            if label == "Степень защиты IP":
                if re.sub(r"\s+", "", claim).upper() in source_matches:
                    continue
            elif _stem_key(claim) in source_matches:
                continue

            key = (label, claim.casefold())
            if key in seen:
                continue

            sentence_start = max(
                generated_text.rfind(".", 0, match.start()),
                generated_text.rfind("!", 0, match.start()),
                generated_text.rfind("?", 0, match.start()),
                generated_text.rfind("\n", 0, match.start()),
            ) + 1
            sentence_ends = [
                position
                for token in (".", "!", "?", "\n")
                if (position := generated_text.find(token, match.end())) >= 0
            ]
            sentence_end = min(sentence_ends) if sentence_ends else len(generated_text)
            context = generated_text[sentence_start:sentence_end].casefold()

            if label in _NO_DISCLAIMER_SKIP:
                disclaimer = _EXPLICIT_NEGATION
            else:
                disclaimer = (
                    _EXPLICIT_NEGATION
                    + r"|требуется подтверждение|нужно подтвердить|необходимо подтвердить|"
                    + r"при необходимости|если требуется|уточните|уточнить|проверьте|проверить|"
                    + r"сверьте|сверить|запросите|запросить|подтвердите|не позволяет|"
                    + r"нельзя делать вывод|не заменяет|следует проверить|рекомендуется сверить|"
                    + r"может потребоваться|не переносите выводы|перед выбором|перед заказом"
                )
            if re.search(disclaimer, context):
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
        "Диапазон температуры измеряемой среды",
        (
            r"(?<!\w)температур\w*\s+диапазон\w*\s+измеряем\w*\s+сред\w*(?!\w)",
            r"(?<!\w)диапазон\w*\s+температур\w*\s+измеряем\w*\s+сред\w*(?!\w)",
            r"(?<!\w)сред\w*\s+(?:с|при)\s+температур\w*",
        ),
    ),
    (
        "Диапазон температуры окружающего воздуха",
        (
            r"(?<!\w)температур\w*\s+диапазон\w*\s+окружающ\w*\s+воздух\w*(?!\w)",
            r"(?<!\w)диапазон\w*\s+температур\w*\s+окружающ\w*\s+воздух\w*(?!\w)",
        ),
    ),
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
            r"(?<!\w)токов\w*\s+выход\w*(?!\w)",
            r"(?<!\w)output\s+signal(?!\w)",
            r"(?<!\w)output(?!\w)",
        ),
    ),
)
_SPEC_NUMBER_RE = re.compile(r"(?<![\w])[-−+]?\d+(?:[.,]\d+)?(?![\w])")
_VERBAL_SIGN_NUMBER_RE = re.compile(
    r"(?P<sign>минус|плюс|отрицательн\w*|положительн\w*)\s+"
    r"(?P<number>\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_SPEC_UNIT_RE = re.compile(
    r"(?<![\w])(?P<number>[-−+]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>градус\w*\s+цельси\w*|градус\w*\s+фаренгейт\w*|"
    r"degrees?\s+celsius|degrees?\s+fahrenheit|°\s*[cсfф]|м³/ч|м3/ч|л/мин|л/ч|мпа|кпа|гпа|па|бар|атм|"
    r"мм|см|мкм|нм|км|м|ма|квт|вт|мв|кв|кг|мг|г|мл|л|(?-i:В|А)|"
    r"khz|mhz|ghz|hz|mpa|kpa|gpa|pa|bar|atm|mm|cm|um|nm|km|"
    r"ma|kw|w|mv|kv|(?-i:V|A)|kg|mg|g|ml|l)"
    r"(?![\w])",
    re.IGNORECASE,
)


def _normalize_number(value: str, sign: str = "") -> str:
    number = float(value.replace(",", ".").replace("−", "-"))
    if sign.casefold().startswith(("минус", "отриц")):
        number = -abs(number)
    return format(number, ".12g")


def _normalized_numbers(text: str) -> set[str]:
    values: set[str] = set()
    verbal_sign_spans: list[tuple[int, int]] = []
    for match in _VERBAL_SIGN_NUMBER_RE.finditer(text):
        verbal_sign_spans.append(match.span("number"))
        values.add(_normalize_number(match.group("number"), match.group("sign")))
    for match in _SPEC_NUMBER_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in verbal_sign_spans):
            continue
        values.add(_normalize_number(match.group(0)))
    return values


def _normalized_pairs(text: str) -> set[tuple[str, str]]:
    return {
        (
            format(float(match.group("number").replace(",", ".").replace("−", "-")), ".12g"),
            _normalize_spec_unit(match.group("unit")),
        )
        for match in _SPEC_UNIT_RE.finditer(text)
    }


def _normalize_spec_unit(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.casefold())
    if normalized.startswith("градус") or normalized.startswith("degree"):
        return "°c" if "цельс" in normalized or "celsius" in normalized else "°f"
    if normalized == "°с":
        return "°c"
    if normalized == "°ф":
        return "°f"
    return normalized


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


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9«])|\n+")


def drop_flagged_sentences(
    text: str,
    source_text: str,
    product: ProductInput | None,
    field: str,
) -> str:
    """Remove whole sentences that carry unconfirmed claims or mismatched values.

    Sentences are never rewritten: a sentence is kept verbatim or dropped.
    """
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if audit_text_claims(sentence, source_text, field):
            continue
        if product is not None and audit_spec_value_mismatches(sentence, product, field):
            continue
        kept.append(sentence)
    return " ".join(kept)
