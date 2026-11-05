import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pypdf import PdfReader

from app.schemas import ProductInput

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_CATALOG_PRODUCTS = 10
MAX_PDF_PAGES = 30
MAX_PDF_TEXT_CHARS = 30_000

_FIELD_ALIASES = {
    "name": {"name", "название", "наименование", "товар", "модель", "обозначение"},
    "manufacturer": {"manufacturer", "производитель", "изготовитель"},
    "category": {"category", "категория", "тип прибора"},
    "description": {"description", "описание", "назначение"},
}


def _header_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold().replace("_", " ").replace("-", " "))


def _cell_value(value: Any) -> str | int | float | bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    cleaned = str(value).strip()
    return cleaned or None


def _row_to_product(headers: list[str], values: list[Any]) -> ProductInput:
    payload: dict[str, Any] = {"specs": {}}
    specs: dict[str, Any] = {}

    for header, raw_value in zip(headers, values, strict=False):
        value = _cell_value(raw_value)
        if value is None:
            continue
        token = _header_token(header)
        if not token:
            continue

        matched_field = next(
            (field for field, aliases in _FIELD_ALIASES.items() if token in aliases),
            None,
        )
        if matched_field:
            payload[matched_field] = str(value)
            continue

        if token.startswith("spec "):
            key = str(header).strip()[5:].strip()
        elif token.startswith("характеристика "):
            key = str(header).strip()[15:].strip()
        else:
            key = str(header).strip()
        if key:
            specs[key] = value

    payload["specs"] = specs
    if not payload.get("name"):
        raise ValueError("не заполнено обязательное поле «Название»")
    return ProductInput.model_validate(payload)


def _catalog_rows_from_csv(content: bytes) -> tuple[list[str], list[list[Any]]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            decoded = content.decode("cp1251")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV должен быть в UTF-8 или Windows-1251") from exc

    sample = decoded[:8192]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","

    rows = list(csv.reader(io.StringIO(decoded), delimiter=delimiter))
    if not rows or not any(str(cell).strip() for cell in rows[0]):
        raise ValueError("В CSV отсутствует строка заголовков")
    headers = [str(cell or "").strip() for cell in rows[0]]
    return headers, rows[1:]


def _catalog_rows_from_xlsx(content: bytes) -> tuple[list[str], list[list[Any]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            expanded_size = sum(item.file_size for item in archive.infolist())
            if expanded_size > 30 * 1024 * 1024:
                raise ValueError("Распакованный XLSX превышает допустимый размер 30 МБ")
    except zipfile.BadZipFile as exc:
        raise ValueError("Файл XLSX повреждён или имеет неверный формат") from exc

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("Не удалось открыть XLSX. Проверьте файл и его структуру.") from exc

    try:
        worksheet = workbook.active
        iterator = worksheet.iter_rows(values_only=True)
        first = next(iterator, None)
        if not first or not any(value is not None and str(value).strip() for value in first):
            raise ValueError("В XLSX отсутствует строка заголовков")
        headers = [str(value or "").strip() for value in first]
        return headers, [list(row) for row in iterator]
    finally:
        workbook.close()


def parse_catalog_file(file_name: str, content: bytes) -> dict[str, Any]:
    """Parse a small CSV/XLSX catalogue into validated ProductInput rows."""
    if not content:
        raise ValueError("Файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Размер файла превышает 8 МБ")

    suffix = Path(file_name or "").suffix.casefold()
    if suffix == ".csv":
        headers, rows = _catalog_rows_from_csv(content)
    elif suffix == ".xlsx":
        headers, rows = _catalog_rows_from_xlsx(content)
    else:
        raise ValueError("Поддерживаются только файлы CSV и XLSX")

    products: list[ProductInput] = []
    warnings: list[str] = []
    errors: list[str] = []

    for row_number, row in enumerate(rows, start=2):
        if not any(value is not None and str(value).strip() for value in row):
            continue
        if len(products) >= MAX_CATALOG_PRODUCTS:
            warnings.append(
                f"Импортированы первые {MAX_CATALOG_PRODUCTS} товаров. "
                "Оставшиеся строки не обработаны из-за лимита пакетной генерации."
            )
            break
        try:
            products.append(_row_to_product(headers, list(row)))
        except Exception as exc:
            errors.append(f"Строка {row_number}: {str(exc)[:240]}")

    if not products:
        raise ValueError(
            "Не удалось импортировать товары. Проверьте заголовки и обязательную колонку «Название»."
        )
    if errors:
        warnings.append(f"Пропущено строк с ошибками: {len(errors)}.")
    return {
        "imported_count": len(products),
        "products": products,
        "warnings": warnings,
        "errors": errors,
    }


_PDF_LABEL_RE = re.compile(r"^\s*([^:：]{2,80}?)\s*[:：]\s*(.{1,1000})\s*$")
_SKIP_SPEC_LABELS = {
    "наименование", "название", "модель", "обозначение", "тип",
    "производитель", "изготовитель", "назначение", "адрес",
    "телефон", "дата", "номер",
}


def parse_passport_pdf(file_name: str, content: bytes) -> dict[str, Any]:
    """Extract text and simple key/value lines from a searchable PDF passport.

    OCR is intentionally out of scope: scanned image-only PDFs return a clear
    error instead of silently creating an empty product.
    """
    if not content:
        raise ValueError("PDF-файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Размер PDF превышает 8 МБ")
    if not content.startswith(b"%PDF"):
        raise ValueError("Файл не похож на PDF")

    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
    except Exception as exc:
        raise ValueError("Не удалось открыть PDF. Проверьте файл.") from exc

    if getattr(reader, "is_encrypted", False):
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:
            raise ValueError("PDF защищён паролем; загрузите незашифрованный файл.") from exc
        if not unlocked:
            raise ValueError("PDF защищён паролем; загрузите незашифрованный файл.")

    page_count = len(reader.pages)
    if page_count < 1:
        raise ValueError("В PDF нет страниц")
    if page_count > MAX_PDF_PAGES:
        raise ValueError(f"PDF содержит больше {MAX_PDF_PAGES} страниц; для MVP лимит — 30")

    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    extracted_text = "\n".join(chunks).strip()
    if not extracted_text:
        raise ValueError(
            "Не удалось извлечь текст. Возможно, это скан: OCR в тестовой версии не поддерживается."
        )

    lines = [re.sub(r"\s+", " ", line).strip() for line in extracted_text.splitlines()]
    lines = [line for line in lines if line]
    name = ""
    manufacturer = ""
    description = None
    specs: dict[str, str] = {}

    for line in lines:
        match = _PDF_LABEL_RE.match(line)
        if not match:
            continue
        label, value = match.group(1).strip(), match.group(2).strip()
        token = _header_token(label)
        if token in {"наименование", "название", "модель", "обозначение", "тип"} and not name:
            name = value
        elif token in {"производитель", "изготовитель"} and not manufacturer:
            manufacturer = value
        elif token == "назначение" and not description:
            description = value
        elif token not in _SKIP_SPEC_LABELS and len(specs) < 60:
            specs[label[:100]] = value[:1000]

    if not name:
        candidates = [
            line for line in lines
            if not re.search(r"паспорт|руководство|содержание|технические условия", line, re.I)
        ]
        name = candidates[0] if candidates else Path(file_name).stem

    product = ProductInput(
        name=(name or Path(file_name).stem or "Товар из паспорта")[:200],
        manufacturer=manufacturer[:200] or None,
        description=description[:3000] if description else None,
        specs=specs,
    )
    warnings = [
        "Поля извлечены автоматически по тексту PDF. Проверьте каждое значение по оригинальному паспорту."
    ]
    if not specs:
        warnings.append(
            "Не найдены строки вида «Характеристика: значение». Добавьте характеристики вручную."
        )
    return {
        "file_name": file_name,
        "page_count": page_count,
        "product": product,
        "extracted_text": extracted_text[:MAX_PDF_TEXT_CHARS],
        "warnings": warnings,
    }
