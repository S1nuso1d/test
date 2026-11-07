import re
from typing import Any

from app.services.claim_audit import (
    audit_draft_claims,
    audit_spec_value_mismatches,
    audit_text_claims,
    find_spec_labels,
)

from app.schemas import (
    KeyCharacteristic,
    LLMProductCopy,
    MissingDataReport,
    ProductInput,
)

DATA_NOT_AVAILABLE = "данных нет"
_NUMBER_PATTERN = re.compile(r"(?<![\w])[-−+]?\d+(?:[.,]\d+)?(?![\w])")
_NUMBER_UNIT_PATTERN = re.compile(
    r"(?<![\w])(?P<number>[-−+]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>градус\w*\s+цельси\w*|градус\w*\s+фаренгейт\w*|"
    r"degrees?\s+celsius|degrees?\s+fahrenheit|°\s*[cсfф]|м³/ч|м3/ч|л/мин|л/ч|мпа|кпа|гпа|па|бар|атм|"
    r"мм|см|мкм|нм|км|м|ма|квт|вт|мв|кв|кг|мг|г|мл|л|"
    r"кгц|мгц|ггц|гц|%|(?-i:В|А)|mpa|kpa|gpa|pa|bar|atm|mm|cm|um|nm|km|"
    r"ma|kw|w|mv|kv|(?-i:V|A)|kg|mg|g|ml|l|khz|mhz|ghz|hz)"
    r"(?![\w])",
    re.IGNORECASE,
)

# Expected fields are category-specific. This avoids asking for a power supply on
# a purely mechanical pressure gauge, while still surfacing useful omissions.
CATEGORY_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "pressure_gauge": {
        "Диапазон измерений": ("диапазон", "предел измерения", "measurement range", "range"),
        "Класс точности": ("класс точности", "точность", "accuracy class", "accuracy"),
        "Присоединение": ("присоединение", "резьб", "connection", "thread"),
        "Диаметр корпуса": ("диаметр корпуса", "диаметр циферблата", "case diameter", "dial diameter"),
    },
    "temperature_transmitter": {
        "Диапазон измерений": ("диапазон", "предел измерения", "measurement range", "range"),
        "Тип входного датчика": ("тип датчика", "термосопротивлен", "термопар", "sensor type", "input sensor"),
        "Выходной сигнал": ("выходной сигнал", "сигнал выхода", "output signal", "output"),
        "Напряжение питания": ("питание", "напряжение", "supply voltage", "power supply"),
        "Класс точности": ("класс точности", "точность", "accuracy class", "accuracy"),
        "Степень защиты": ("степень защиты", "ip rating", "ingress protection"),
    },
    "temperature_sensor": {
        "Диапазон измерений": ("диапазон", "предел измерения", "measurement range", "range"),
        "Тип чувствительного элемента": ("тип датчика", "чувствительный элемент", "термопар", "термосопротивлен", "sensor type", "element"),
        "Класс точности": ("класс точности", "точность", "accuracy class", "accuracy"),
        "Присоединение": ("присоединение", "резьб", "connection", "thread"),
    },
    "pressure_transmitter": {
        "Диапазон измерений": ("диапазон", "предел измерения", "measurement range", "range"),
        "Класс точности": ("класс точности", "точность", "accuracy class", "accuracy"),
        "Выходной сигнал": ("выходной сигнал", "сигнал выхода", "токовый выход", "output signal", "output"),
        "Напряжение питания": ("питание", "напряжение", "supply voltage", "power supply"),
        "Присоединение": ("присоединение", "резьб", "connection", "thread"),
        "Степень защиты": ("степень защиты", "ip rating", "ingress protection"),
    },
    "flow_meter": {
        "Диапазон расхода": ("расход", "диапазон измерения", "flow range", "flow rate", "range"),
        "Класс точности": ("класс точности", "точность", "accuracy class", "accuracy"),
        "Присоединение": ("присоединение", "диаметр условного прохода", "connection", "nominal diameter"),
        "Выходной сигнал": ("выходной сигнал", "сигнал выхода", "output signal", "output"),
        "Напряжение питания": ("питание", "напряжение", "supply voltage", "power supply"),
    },
    "level_sensor": {
        "Диапазон измерений": ("диапазон", "предел измерения", "measurement range", "range"),
        "Принцип измерения": ("принцип измерения", "технология измерения", "measuring principle"),
        "Выходной сигнал": ("выходной сигнал", "сигнал выхода", "output signal", "output"),
        "Напряжение питания": ("питание", "напряжение", "supply voltage", "power supply"),
        "Степень защиты": ("степень защиты", "ip rating", "ingress protection"),
    },
}

CATEGORY_ALIASES = {
    "pressure_gauge": ("pressure_gauge", "манометр", "pressure gauge"),
    "temperature_transmitter": ("temperature_transmitter", "преобразователь температуры", "датчик температуры с выходом", "temperature transmitter"),
    "temperature_sensor": ("temperature_sensor", "термопреобразователь", "термодатчик", "термометр", "temperature sensor", "thermometer"),
    "pressure_transmitter": ("pressure_transmitter", "преобразователь давления", "датчик давления", "pressure transmitter"),
    "flow_meter": ("flow_meter", "расходомер", "flow meter", "flowmeter"),
    "level_sensor": ("level_sensor", "уровнемер", "датчик уровня", "level sensor"),
}

CATEGORY_LABELS = {
    "pressure_gauge": "Манометр",
    "temperature_transmitter": "Преобразователь температуры",
    "temperature_sensor": "Датчик температуры",
    "pressure_transmitter": "Преобразователь давления",
    "flow_meter": "Расходомер",
    "level_sensor": "Датчик уровня",
    "generic": "Не определён",
}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def detect_category(product: ProductInput) -> tuple[str, str]:
    if product.category:
        supplied = product.category.casefold().strip()
        for category, aliases in CATEGORY_ALIASES.items():
            if any(alias.casefold() in supplied for alias in aliases):
                return category, "provided"
        return "generic", "provided"

    haystack = f"{product.name or ''} {product.description or ''}".casefold()
    # More specific classes should be checked before generic temperature/pressure sensors.
    for category in (
        "pressure_gauge",
        "temperature_transmitter",
        "pressure_transmitter",
        "temperature_sensor",
        "flow_meter",
        "level_sensor",
    ):
        if any(alias.casefold() in haystack for alias in CATEGORY_ALIASES[category]):
            return category, "detected"
    return "generic", "generic"


def _has_spec(spec_keys: list[str], aliases: tuple[str, ...]) -> bool:
    return any(alias.casefold() in key for key in spec_keys for alias in aliases)


def find_missing_data(product: ProductInput) -> MissingDataReport:
    category, category_source = detect_category(product)
    fields = [name for name in ("name", "manufacturer", "description") if not getattr(product, name)]
    all_spec_keys = [key.casefold() for key in product.specs]
    empty_specs = [key for key, value in product.specs.items() if value is None or not str(value).strip()]
    expected_specs = [
        label
        for label, aliases in CATEGORY_RULES.get(category, {}).items()
        if not _has_spec(all_spec_keys, aliases)
    ]
    return MissingDataReport(
        category=category,
        category_source=category_source,
        fields=fields,
        empty_specs=empty_specs,
        expected_specs=expected_specs,
    )


def find_missing_fields(product: ProductInput) -> list[str]:
    """Compatibility-friendly flat list for API clients and the web UI."""
    report = find_missing_data(product)
    return report.fields + [f"specs.{key}" for key in report.empty_specs] + report.expected_specs


def build_characteristics(product: ProductInput, missing: MissingDataReport | None = None) -> list[KeyCharacteristic]:
    """Copy supplied specs verbatim and append category-relevant missing parameters."""
    report = missing or find_missing_data(product)
    rows = [
        KeyCharacteristic(name=key, value=_stringify(value) or DATA_NOT_AVAILABLE)
        for key, value in product.specs.items()
    ]
    existing = [key.casefold() for key in product.specs]
    for label in report.expected_specs:
        aliases = CATEGORY_RULES.get(report.category, {}).get(label, ())
        if not _has_spec(existing, aliases):
            rows.append(KeyCharacteristic(name=label, value=DATA_NOT_AVAILABLE))
    if not rows:
        rows.append(KeyCharacteristic(name="Технические характеристики", value=DATA_NOT_AVAILABLE))
    return rows


def build_source_text(product: ProductInput) -> str:
    parts = [product.name or "", product.manufacturer or "", product.category or "", product.description or ""]
    parts.extend(f"{key}: {_stringify(value)}" for key, value in product.specs.items())
    return "\n".join(part for part in parts if part)


_VERBAL_SIGN_NUMBER_PATTERN = re.compile(
    r"(?P<sign>минус|плюс|отрицательн\w*|положительн\w*)\s+"
    r"(?P<number>\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def _normalized_number(value: str, sign: str = "") -> str:
    number = float(value.replace(",", ".").replace("−", "-"))
    if sign.casefold().startswith(("минус", "отриц")):
        number = -abs(number)
    return format(number, ".12g")


def numbers_in(text: str) -> set[str]:
    values: set[str] = set()
    verbal_sign_spans: list[tuple[int, int]] = []
    for match in _VERBAL_SIGN_NUMBER_PATTERN.finditer(text):
        verbal_sign_spans.append(match.span("number"))
        values.add(_normalized_number(match.group("number"), match.group("sign")))
    for match in _NUMBER_PATTERN.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in verbal_sign_spans):
            continue
        values.add(_normalized_number(match.group(0)))
    return values


def find_unsupported_numbers(generated_text: str, source_text: str) -> list[str]:
    """Detect numeric tokens in generated copy that do not occur in the input.

    This conservative lexical check does not prove semantic correctness.
    """
    return sorted(numbers_in(generated_text) - numbers_in(source_text))


def _normalize_quantity_number(value: str) -> str:
    return format(float(value.replace(",", ".").replace("−", "-")), ".12g")


def _normalize_quantity_unit(value: str) -> str:
    normalized = re.sub(r"\s+", "", value.casefold())
    if normalized.startswith("градус") or normalized.startswith("degree"):
        return "°c" if "цельс" in normalized or "celsius" in normalized else "°f"
    if normalized == "°с":
        return "°c"
    if normalized == "°ф":
        return "°f"
    return normalized


def find_unsupported_unit_pairs(generated_text: str, source_text: str) -> list[str]:
    """Detect numeric values paired with units not present in the source.

    This catches errors such as changing 1.6 MPa to 1.6 bar even though the
    numeric token itself is present in the input.
    """
    def extract(text: str) -> set[tuple[str, str]]:
        return {
            (_normalize_quantity_number(match.group("number")),
             _normalize_quantity_unit(match.group("unit")))
            for match in _NUMBER_UNIT_PATTERN.finditer(text)
        }

    unsupported = extract(generated_text) - extract(source_text)
    return [f"{number} {unit}" for number, unit in sorted(unsupported)]


_QUALIFIED_VALUE_RE = re.compile(
    r"^(?P<q>не\s+более|не\s+менее|не\s+выше|не\s+ниже)\s+(?P<tail>\d.*)$", re.IGNORECASE
)
_QUALIFIER_BEFORE_RE = re.compile(
    r"(?:не\s+более|не\s+менее|не\s+выше|не\s+ниже|более|менее|до|от|≤|≥)\s*$",
    re.IGNORECASE,
)


def find_lost_qualifiers(generated_text: str, product: ProductInput) -> list[str]:
    """Detect when a source limit such as 'не более 5 мА' becomes a bare value."""
    issues: list[str] = []
    for key, raw_value in product.specs.items():
        value = _stringify(raw_value).strip()
        match = _QUALIFIED_VALUE_RE.match(value)
        if not match:
            continue
        tail = match.group("tail").split("(")[0].strip()
        pattern = re.compile(
            r"(?<![\w,.])" + r"\s+".join(re.escape(part) for part in tail.split()) + r"(?!\w)",
            re.IGNORECASE,
        )
        for hit in pattern.finditer(generated_text):
            before = generated_text[max(0, hit.start() - 20) : hit.start()]
            if not _QUALIFIER_BEFORE_RE.search(before):
                issues.append(
                    f"Потерян модификатор значения: у параметра «{key}» в источнике "
                    f"«{value», а в тексте «{tail}» без «{match.group('q')}»"
                )
                break
    return issues


def all_generated_text(draft: LLMProductCopy) -> str:
    sales = draft.sales_section
    pieces = [draft.seo_title, draft.seo_description, *draft.seo_queries]
    pieces += [*sales.suitable_for, *sales.tasks_solved, sales.pitch]
    return "\n".join(piece for piece in pieces if piece)


def validate_generated_copy(
    draft: LLMProductCopy, source_text: str, product: ProductInput | None = None
) -> list[str]:
    issues: list[str] = []
    title = draft.seo_title.strip()
    description = draft.seo_description.strip()
    queries = [item.strip() for item in draft.seo_queries if item and item.strip()]
    sales = draft.sales_section

    if not title:
        issues.append("SEO-заголовок пустой")
    elif len(title) > 70:
        issues.append(f"SEO-заголовок содержит {len(title)} символов; максимум — 70")
    if not 800 <= len(description) <= 1200:
        issues.append(f"SEO-описание содержит {len(description)} символов; требуется 800–1200")
    if not 3 <= len(queries) <= 5:
        issues.append(f"Найдено {len(queries)} непустых поисковых запросов; требуется 3–5")

    normalized_queries = [
        " ".join(re.findall(r"[a-zа-яё0-9]+", item.casefold()))
        for item in queries
    ]
    if len(normalized_queries) != len(set(normalized_queries)):
        issues.append("В списке поисковых запросов есть повторы; оставьте 3–5 уникальных формулировок")
    if not any(item.strip() for item in sales.suitable_for):
        issues.append("В коммерческом блоке не указана целевая аудитория или необходимость её уточнить")
    if not any(item.strip() for item in sales.tasks_solved):
        issues.append("В коммерческом блоке не указаны задачи или необходимость их уточнить")
    if not sales.pitch.strip():
        issues.append("В коммерческом блоке отсутствует краткий тезис для менеджера")

    if product is not None:
        for audience in sales.suitable_for:
            spec_labels = find_spec_labels(audience, product)
            if spec_labels:
                issues.append(
                    "Поле «Кому подходит» должно описывать тип покупателей или специалистов, "
                    "а не технические характеристики. Перенесите параметр "
                    f"«{spec_labels[0]}» в описание или характеристики."
                )

    unsupported = find_unsupported_numbers(all_generated_text(draft), source_text)
    if unsupported:
        issues.append(
            "В сгенерированных полях обнаружены числовые значения, отсутствующие во входных данных: "
            + ", ".join(unsupported)
        )
    unsupported_units = find_unsupported_unit_pairs(all_generated_text(draft), source_text)
    if unsupported_units:
        issues.append(
            "Числовые значения связаны с неподтверждёнными единицами измерения: "
            + ", ".join(unsupported_units)
        )
    if product is not None:
        issues.extend(find_lost_qualifiers(all_generated_text(draft), product))
    for finding in audit_draft_claims(draft, source_text, product):
        issues.append(
            f"{finding.field}: неподтверждённое утверждение «{finding.claim}». "
            f"{finding.message}"
        )
    return issues


def has_substantive_product_data(product: ProductInput) -> bool:
    has_specs = any(value is not None and str(value).strip() for value in product.specs.values())
    return bool(product.name and (product.description or has_specs))


def validate_seo_description(
    description: str, source_text: str, product: ProductInput | None = None
) -> list[str]:
    """Validate only the SEO description so it can be repaired independently."""
    issues: list[str] = []
    cleaned = description.strip()
    if not 800 <= len(cleaned) <= 1200:
        issues.append(
            f"SEO-описание содержит {len(cleaned)} символов; требуется 800–1200"
        )
    unsupported = find_unsupported_numbers(cleaned, source_text)
    if unsupported:
        issues.append(
            "В SEO-описании есть числовые значения, отсутствующие во входных данных: "
            + ", ".join(unsupported)
        )
    unsupported_units = find_unsupported_unit_pairs(cleaned, source_text)
    if unsupported_units:
        issues.append(
            "В SEO-описании указаны неподтверждённые сочетания числа и единицы измерения: "
            + ", ".join(unsupported_units)
        )
    if product is not None:
        issues.extend(find_lost_qualifiers(cleaned, product))
    for finding in audit_text_claims(cleaned, source_text, "SEO-описание"):
        issues.append(
            f"SEO-описание: неподтверждённое утверждение «{finding.claim}». "
            f"{finding.message}"
        )
    if product is not None:
        for finding in audit_spec_value_mismatches(cleaned, product, "SEO-описание"):
            issues.append(
                f"SEO-описание: неподтверждённое значение «{finding.claim}». "
                f"{finding.message}"
            )
    return issues


def compact_seo_description(description: str, product: ProductInput) -> str | None:
    """Shorten overlong SEO copy by removing whole low-value sentences only.

    Sentences are never rewritten. Sentences with unsupported claims or mismatched
    values are excluded; the result must still pass the regular validator.
    """
    cleaned = re.sub(r"\s+", " ", description).strip()
    if len(cleaned) <= 1200:
        return cleaned if len(cleaned) >= 800 else None

    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z0-9«])", cleaned)
        if item.strip()
    ]
    if len(sentences) < 2:
        return None

    source_text = build_source_text(product)
    source_numbers = numbers_in(source_text)
    ranked: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        if audit_text_claims(sentence, source_text, "SEO-описание"):
            continue
        if audit_spec_value_mismatches(sentence, product, "SEO-описание"):
            continue

        score = 10 if index == 0 else 0
        score += 6 * len(find_spec_labels(sentence, product))
        score += 2 * min(len(numbers_in(sentence) & source_numbers), 5)
        if re.search(r"предназначен|измерени|контрол\w*|передач\w*|выход\w*", sentence, re.IGNORECASE):
            score += 2
        if re.search(r"поставщик|уточн|свер|проверь|перед выбором", sentence, re.IGNORECASE):
            score += 1
        if re.search(r"не заменяет|описание основано|перед публикацией|в целом|при этом", sentence, re.IGNORECASE):
            score -= 2
        ranked.append((score, index, sentence))

    if not ranked or not any(index == 0 for _, index, _ in ranked):
        return None
    chosen: list[tuple[int, int, str]] = [next(item for item in ranked if item[1] == 0)]
    current_length = len(chosen[0][2])
    remaining = sorted(
        (entry for entry in ranked if entry[1] != 0),
        key=lambda entry: (-entry[0], entry[1]),
    )
    for item in remaining:
        candidate_length = current_length + 1 + len(item[2])
        if candidate_length <= 1200:
            chosen.append(item)
            current_length = candidate_length

    result = " ".join(sentence for _, _, sentence in sorted(chosen, key=lambda entry: entry[1]))
    return result if 800 <= len(result) <= 1200 else None


def build_safe_seo_description(product: ProductInput) -> str:
    """Build a transparent, fact-safe fallback from source data and buyer checklists.

    The text describes no new product properties: generic passages are framed as
    checks the buyer should perform, not as claims about the instrument.
    """
    name = product.name or "Указанный прибор"
    identity = f"В исходных данных указан товар «{name}»."
    if product.manufacturer:
        identity += f" Производитель — {product.manufacturer}."

    source_description = (product.description or "").strip()
    if len(source_description) > 260:
        source_description = source_description[:257].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    if source_description:
        identity += f" В описании указано: {source_description}"

    values = [
        (str(key).strip(), _stringify(value).strip())
        for key, value in product.specs.items()
        if value is not None and _stringify(value).strip()
    ]
    blocks = [identity]
    if values:
        summary = "В карточке приведены характеристики: " + "; ".join(
            f"{key} — {value}" for key, value in values[:5]
        ) + "."
        blocks.append(summary)

    hints: list[str] = []
    for key, value in values:
        normalized = key.casefold()
        if any(token in normalized for token in ("диапазон", "range", "предел измер")):
            hint = (
                f"Параметр «{key}» ({value}) сопоставьте с ожидаемыми условиями измерения "
                "и требованиями процесса. Допустимый режим проверьте по паспорту: "
                "указанное значение само по себе не подтверждает пригодность для конкретной установки."
            )
        elif any(token in normalized for token in ("точност", "accuracy")):
            hint = (
                f"Параметр «{key}» ({value}) сравните с требованиями к измерительной задаче. "
                "Одно обозначение не позволяет делать выводы о поверке, межповерочном "
                "интервале или погрешности в конкретных условиях."
            )
        elif any(token in normalized for token in ("присоедин", "резьб", "connection", "thread")):
            hint = (
                f"Значение «{key}» ({value}) сверьте с ответной частью и монтажной документацией. "
                "Исходные данные не подтверждают совместимость по типу резьбы, уплотнению "
                "и другим параметрам узла."
            )
        elif any(token in normalized for token in ("диаметр", "размер", "габарит", "diameter", "size")):
            hint = (
                f"Параметр «{key}» ({value}) используйте для предварительной проверки компоновки. "
                "Для окончательного решения могут потребоваться чертёж и установочные размеры; "
                "по одному значению нельзя подтвердить возможность монтажа."
            )
        else:
            hint = (
                f"Параметр «{key}» ({value}) сопоставьте с требованиями вашей задачи и паспортом "
                "изделия. Не переносите выводы о свойствах и совместимости с похожих моделей."
            )
        hints.append(hint)

    for hint in hints:
        candidate = " ".join(blocks + [hint])
        if len(candidate) <= 1180:
            blocks.append(hint)

    missing = find_missing_data(product)
    if missing.expected_specs:
        paragraph = (
            "В исходных данных не указаны ожидаемые параметры: "
            + ", ".join(missing.expected_specs[:5])
            + ". Запросите их у поставщика, если они важны для выбора."
        )
        if len(" ".join(blocks + [paragraph])) <= 1200:
            blocks.append(paragraph)

    extras = [
        (
            "При сравнении предложений используйте одинаковые критерии и проверяйте, "
            "что сведения относятся именно к указанной модели, а не к другой модификации."
        ),
        (
            "Перед оформлением заказа подтвердите полное обозначение модели, состав поставки "
            "и наличие нужной документации. Отсутствующие значения не следует заменять предположениями."
        ),
        (
            "Описание основано только на переданных сведениях, не подтверждает совместимость "
            "с конкретной системой и не заменяет паспорт изделия или консультацию производителя."
        ),
        (
            "Если для выбора требуется дополнительный параметр, зафиксируйте его как вопрос "
            "к поставщику и дождитесь документального подтверждения до согласования заказа."
        ),
    ]
    for extra in extras:
        current = " ".join(blocks)
        if len(current) >= 800:
            break
        if len(current + " " + extra) <= 1200:
            blocks.append(extra)

    result = " ".join(blocks).strip()
    while len(result) > 1200 and len(blocks) > 1:
        blocks.pop()
        result = " ".join(blocks).strip()

    if not 800 <= len(result) <= 1200:
        raise ValueError(
            "Не удалось безопасно сформировать SEO-описание длиной 800–1200 символов."
        )
    return result


def calculate_quality_score(
    draft: LLMProductCopy, source_text: str, product: ProductInput | None = None
) -> int:
    """Return a formal checklist score; it is not a semantic truthfulness score."""
    score = 0
    title = draft.seo_title.strip()
    description = draft.seo_description.strip()
    queries = [item.strip() for item in draft.seo_queries if item and item.strip()]
    sales = draft.sales_section

    if title and len(title) <= 70:
        score += 15
    if 800 <= len(description) <= 1200:
        score += 30
    normalized_queries = [
        " ".join(re.findall(r"[a-zа-яё0-9]+", item.casefold()))
        for item in queries
    ]
    if 3 <= len(queries) <= 5 and len(normalized_queries) == len(set(normalized_queries)):
        score += 15
    if sales.suitable_for and any(item.strip() for item in sales.suitable_for):
        score += 10
    if sales.tasks_solved and any(item.strip() for item in sales.tasks_solved):
        score += 10
    if sales.pitch.strip():
        score += 10
    generated_text = all_generated_text(draft)
    has_numeric_issues = bool(find_unsupported_numbers(generated_text, source_text))
    has_unit_issues = bool(find_unsupported_unit_pairs(generated_text, source_text))
    has_claim_issues = bool(audit_draft_claims(draft, source_text, product))
    if not has_numeric_issues and not has_unit_issues and not has_claim_issues:
        score += 10
    return score
