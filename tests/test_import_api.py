from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_catalog_import_endpoint_accepts_csv_upload() -> None:
    content = (
        "Название;Производитель;Диапазон измерений\n"
        "Манометр DM 02;Манотомь;0–1,6 МПа\n"
    ).encode("utf-8")

    response = client.post(
        "/api/import/catalog",
        files={"file": ("catalog.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["products"][0]["name"] == "Манометр DM 02"


def test_catalog_import_endpoint_rejects_wrong_extension() -> None:
    response = client.post(
        "/api/import/catalog",
        files={"file": ("catalog.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_passport_import_endpoint_rejects_invalid_pdf() -> None:
    response = client.post(
        "/api/import/passport",
        files={"file": ("passport.pdf", b"not a pdf", "application/pdf")},
    )
    assert response.status_code == 400
