"""Run real Ollama generations and prepare evidence for the assignment submission.

This script talks only to the locally running Product Copy AI API. It never
fabricates a result: every saved card is the API response for the supplied input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCT = ROOT / "examples" / "product_dm_02.json"
DEFAULT_OUTPUT = ROOT / "examples" / "results"
REQUIRED_PRODUCT_COUNT = 2


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _slug(value: str, fallback: str = "product") -> str:
    slug = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ]+", "-", value.casefold()).strip("-")
    return slug[:60] or fallback


def load_product(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Не удалось прочитать JSON товара {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Файл {path} должен содержать JSON-объект одного товара.")
    if not value.get("name"):
        raise ValueError(f"В файле {path} отсутствует обязательное поле name.")
    return value


def evaluate_result(product: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """Apply transparent deterministic submission checks to one API response."""
    issues: list[str] = []
    title = str(result.get("seo_title") or "")
    description = str(result.get("seo_description") or "")
    queries = result.get("seo_queries") or []
    sales = result.get("sales_section") or {}

    if not title:
        issues.append("Не сформирован SEO-заголовок.")
    elif len(title) > 70:
        issues.append(f"SEO-заголовок длиннее 70 символов: {len(title)}.")

    if not 800 <= len(description) <= 1200:
        issues.append(f"Длина SEO-описания {len(description)} символов вместо 800–1200.")

    if not isinstance(queries, list) or not 3 <= len(queries) <= 5:
        issues.append("Количество поисковых запросов должно быть от 3 до 5.")
    elif len({_normalized(item) for item in queries if _normalized(item)}) != len(queries):
        issues.append("В поисковых запросах есть пустые значения или повторы.")

    suitable_for = sales.get("suitable_for") or []
    tasks_solved = sales.get("tasks_solved") or []
    if not 1 <= len(suitable_for) <= 4:
        issues.append("В блоке «Кому подходит» должно быть от 1 до 4 пунктов.")
    if not 1 <= len(tasks_solved) <= 4:
        issues.append("В блоке «Решаемые задачи» должно быть от 1 до 4 пунктов.")
    if not str(sales.get("pitch") or "").strip():
        issues.append("Не заполнены тезисы для менеджера.")

    if any(
        re.search(r"\d|\b(?:МПа|кПа|бар|мм|см|°C|В|мА|IP\d{2})\b", str(item), re.I)
        for item in suitable_for
    ):
        issues.append("В поле «Кому подходит» обнаружен числовой или технический параметр.")

    expected_specs = product.get("specs") or {}
    actual_specs = {
        (_normalized(item.get("name")), _normalized(item.get("value")))
        for item in (result.get("key_characteristics") or [])
        if isinstance(item, dict)
    }
    for name, value in expected_specs.items():
        if value is None or str(value).strip() == "":
            continue
        if (_normalized(name), _normalized(value)) not in actual_specs:
            issues.append(f"Исходная характеристика «{name}: {value}» не перенесена точно.")

    missing_data = result.get("missing_data") or {}
    for expected_name in missing_data.get("expected_specs") or []:
        rows = [
            item for item in (result.get("key_characteristics") or [])
            if isinstance(item, dict)
            and _normalized(item.get("name")) == _normalized(expected_name)
        ]
        if not rows or not any(_normalized(item.get("value")) == "данных нет" for item in rows):
            issues.append(
                f"Для отсутствующей характеристики «{expected_name}» не указано «данных нет»."
            )

    findings = result.get("fact_check_findings") or []
    if findings:
        issues.append(f"Автоматическая проверка нашла неподтверждённые утверждения: {len(findings)}.")
    validation_errors = result.get("validation_errors") or []
    if validation_errors:
        issues.append(f"Остались формальные ошибки: {len(validation_errors)}.")
    if result.get("seo_fallback_used"):
        issues.append("Использован резервный SEO-шаблон вместо полноценного текста модели.")
    if result.get("status") != "generated":
        issues.append(f"Статус результата — {result.get('status')!r}, ожидается 'generated'.")

    return issues


def _markdown_fallback(product: dict[str, Any], result: dict[str, Any]) -> str:
    sales = result.get("sales_section") or {}
    lines = [
        f"# {result.get('product_name') or product.get('name') or 'Товар'}",
        "",
        f"**Производитель:** {result.get('manufacturer') or product.get('manufacturer') or 'Не указан'}",
        "",
        "## SEO-заголовок",
        str(result.get("seo_title") or ""),
        "",
        "## SEO-описание",
        str(result.get("seo_description") or ""),
        "",
        "## Ключевые характеристики",
    ]
    for item in result.get("key_characteristics") or []:
        lines.append(f"- **{item.get('name', '')}:** {item.get('value', '')}")
    lines.extend(["", "## Поисковые запросы"])
    for query in result.get("seo_queries") or []:
        lines.append(f"- {query}")
    lines.extend(["", "## Коммерческий блок", "### Кому подходит"])
    for item in sales.get("suitable_for") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### Решаемые задачи"])
    for item in sales.get("tasks_solved") or []:
        lines.append(f"- {item}")
    lines.extend(["", "### Тезисы для менеджера", str(sales.get("pitch") or ""), ""])
    return "\n".join(lines)


def run_check(
    product_paths: list[Path],
    output_dir: Path,
    base_url: str,
    timeout_seconds: float,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    products: list[tuple[Path, dict[str, Any]]] = []
    load_errors: list[str] = []
    for raw_path in product_paths:
        path = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
        if not path.exists():
            path = ROOT / raw_path
        try:
            products.append((path, load_product(path)))
        except ValueError as exc:
            load_errors.append(str(exc))

    report_lines = [
        "# Отчёт проверки перед сдачей тестового задания",
        "",
        f"- Дата запуска (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- API: `{base_url}`",
        f"- Передано файлов товаров: {len(product_paths)}",
        f"- Успешно прочитано товаров: {len(products)}",
        "",
        "> Автоматическая проверка не заменяет проверку контент-менеджером и сверку с паспортом.",
        "",
    ]
    for error in load_errors:
        report_lines.append(f"- Ошибка входного файла: {error}")

    if len(products) < REQUIRED_PRODUCT_COUNT:
        report_lines.extend([
            "## Комплектность примеров",
            "",
            f"НЕ ЗАКРЫТО: для задания требуются два реальных товара, передано {len(products)}.",
            "Не используйте синтетический демонстрационный товар как замену второму товару из задания.",
            "Добавьте второй JSON, полученный от работодателя, и повторите запуск с двумя путями.",
            "",
        ])

    results_summary: list[dict[str, Any]] = []
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_seconds) as client:
            health = client.get("/health")
            health.raise_for_status()
            status_response = client.get("/api/status")
            status_response.raise_for_status()
            model_info = status_response.json()
            report_lines.insert(5, f"- Модель Ollama: `{model_info.get('model', 'неизвестна')}`")

            for index, (path, product) in enumerate(products, start=1):
                name = str(product.get("name") or f"product-{index}")
                slug = _slug(name, f"product-{index}")
                if any(item["slug"] == slug for item in results_summary):
                    slug = f"{slug}-{index}"
                report_lines.extend([f"## {index}. {name}", "", f"Источник: `{path.name}`", ""])
                try:
                    response = client.post("/api/generate", json=product)
                    response.raise_for_status()
                    result = response.json()
                    issues = evaluate_result(product, result)

                    (output_dir / f"{slug}.json").write_text(
                        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    markdown = _markdown_fallback(product, result)
                    try:
                        export = client.post("/api/export/markdown", json=result)
                        export.raise_for_status()
                        markdown = export.text
                    except httpx.HTTPError:
                        pass
                    (output_dir / f"{slug}.md").write_text(
                        markdown.rstrip() + "\n", encoding="utf-8"
                    )

                    results_summary.append({"slug": slug, "name": name, "issues": issues})
                    report_lines.append(
                        "**Автоматические проверки:** "
                        + ("ПРОЙДЕНЫ" if not issues else "ЕСТЬ ЗАМЕЧАНИЯ")
                    )
                    report_lines.append(f"- Статус API: `{result.get('status')}`")
                    report_lines.append(
                        f"- SEO Title: {len(str(result.get('seo_title') or ''))} символов"
                    )
                    report_lines.append(
                        f"- SEO Description: {len(str(result.get('seo_description') or ''))} символов"
                    )
                    report_lines.append(f"- Поисковых запросов: {len(result.get('seo_queries') or [])}")
                    report_lines.append(f"- Попыток генерации: {result.get('attempts', 0)}")
                    for issue in issues:
                        report_lines.append(f"- Замечание: {issue}")
                    for warning in result.get("warnings") or []:
                        report_lines.append(f"- Предупреждение API: {warning}")
                    report_lines.append("")
                except httpx.HTTPError as exc:
                    message = f"Ошибка API для товара {name}: {exc}"
                    results_summary.append({"slug": slug, "name": name, "issues": [message]})
                    report_lines.extend([f"**ОШИБКА:** {message}", ""])
    except httpx.HTTPError as exc:
        report_lines.extend([
            "## Ошибка подключения",
            "",
            f"Не удалось обратиться к приложению: {exc}",
            "",
        ])
        (output_dir / "submission_report.md").write_text(
            "\n".join(report_lines), encoding="utf-8"
        )
        print(
            "Не удалось подключиться к Product Copy AI API. Проверьте, что сервер запущен.",
            file=sys.stderr,
        )
        return 2

    all_products_pass = (
        len(products) == REQUIRED_PRODUCT_COUNT
        and len(results_summary) == REQUIRED_PRODUCT_COUNT
    )
    all_results_pass = all_products_pass and all(
        not item["issues"] for item in results_summary
    )
    report_lines.extend([
        "## Итог",
        "",
        f"- Проверок пройдено без замечаний: "
        f"{sum(not item['issues'] for item in results_summary)} из {len(results_summary)}.",
        f"- Примеры для двух товаров: "
        f"{'есть' if len(products) == REQUIRED_PRODUCT_COUNT else 'не хватает'}.",
        "- Решение о публикации карточки принимает человек после сверки с исходными документами.",
        "",
        (
            "**Автоматический комплект проверок пройден. Нужна финальная ручная редакторская проверка.**"
            if all_results_pass
            else "**К отправке ещё не готово: устраните замечания и/или добавьте второй реальный товар.**"
        ),
        "",
    ])
    report_path = output_dir / "submission_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"Отчёт: {report_path}")
    print(f"Результаты: {output_dir}")
    print(
        "Автоматические проверки: "
        + ("пройдены" if all_results_pass else "есть незакрытые пункты")
    )
    return 0 if all_results_pass else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Сгенерировать реальные примеры через локальный Product Copy AI и проверить требования ТЗ."
    )
    parser.add_argument(
        "--products",
        nargs="+",
        type=Path,
        default=[DEFAULT_PRODUCT],
        help="Пути к JSON-файлам товаров. Для полного комплекта укажите два реальных товара.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=360.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(
        run_check(args.products, args.output_dir, args.base_url, args.timeout)
    )
