import io

import pytest
from openpyxl import Workbook

from app.services import importers


def test_csv_import_supports_russian_headers_and_semicolon_delimiter() -> None:
    content = (
        "Название;Производитель;Категория;Диапазон измерений;Класс точности\n"
        "Манометр DM 02;Манотомь;pressure_gauge;0–1,6 МПа;1,5\n"
    ).encode("utf-8-sig")

    result = importers.parse_catalog_file("catalog.csv", content)

    assert result["imported_count"] == 1
    product = result["products"][0]
    assert product.name == "Манометр DM 02"
    assert product.manufacturer == "Манотомь"
    assert product.specs["Диапазон измерений"] == "0–1,6 МПа"


def test_xlsx_import_reads_product_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Название", "Производитель", "Диаметр корпуса"])
    sheet.append(["Манометр DM 02", "Манотомь", "100 мм"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    result = importers.parse_catalog_file("catalog.xlsx", buffer.getvalue())

    assert result["imported_count"] == 1
    assert result["products"][0].specs["Диаметр корпуса"] == "100 мм"


def test_catalog_import_rejects_unsupported_extension() -> None:
    with pytest.raises(ValueError, match="CSV и XLSX"):
        importers.parse_catalog_file("catalog.xls", b"not an excel file")


def test_catalog_import_skips_invalid_rows_and_keeps_valid_rows() -> None:
    content = (
        "Название;Класс точности\n"
        "Манометр DM 02;1,5\n"
        ";0,5\n"
    ).encode("utf-8")

    result = importers.parse_catalog_file("catalog.csv", content)
    assert result["imported_count"] == 1
    assert len(result["errors"]) == 1


def test_pdf_passport_extracts_labelled_fields(monkeypatch) -> None:
    sample = (
        "Технический паспорт\n"
        "Наименование: Манометр показывающий DM 02\n"
        "Производитель: Манотомь\n"
        "Назначение: Измерение избыточного давления\n"
        "Диапазон измерений: 0–1,6 МПа\n"
        "Класс точности: 1,5\n"
        "Присоединение: G1/2\n"
    )

    class FakePage:
        def extract_text(self):
            return sample

    class FakeReader:
        def __init__(self, stream, strict=False):
            self.pages = [FakePage()]
            self.is_encrypted = False

    monkeypatch.setattr(importers, "PdfReader", FakeReader)
    result = importers.parse_passport_pdf("passport.pdf", b"%PDF-fake")

    assert result["page_count"] == 1
    assert result["product"].name == "Манометр показывающий DM 02"
    assert result["product"].manufacturer == "Манотомь"
    assert result["product"].description == "Измерение избыточного давления"
    assert result["product"].specs["Диапазон измерений"] == "0–1,6 МПа"


def test_pdf_passport_reports_scanned_pdf_when_no_text_is_available(monkeypatch) -> None:
    class FakePage:
        def extract_text(self):
            return ""

    class FakeReader:
        def __init__(self, stream, strict=False):
            self.pages = [FakePage()]
            self.is_encrypted = False

    monkeypatch.setattr(importers, "PdfReader", FakeReader)
    with pytest.raises(ValueError, match="OCR"):
        importers.parse_passport_pdf("scan.pdf", b"%PDF-fake")
