import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.config import Settings
from app.services.llm_client import LLMClient, LLMConfigurationError, LLMClientError


@pytest.mark.asyncio
async def test_test_connection_uses_configured_local_model(monkeypatch) -> None:
    calls = {}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            calls["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def chat(self, **kwargs):
            calls["request"] = kwargs
            return SimpleNamespace(message=SimpleNamespace(content="OK"))

    fake_module = ModuleType("ollama")
    fake_module.AsyncClient = FakeAsyncClient
    fake_module.ResponseError = type("ResponseError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    settings = Settings(
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen2.5:14b",
    )
    result = await LLMClient(settings).test_connection()

    assert result == "OK"
    assert calls["client_kwargs"]["host"] == "http://127.0.0.1:11434"
    assert calls["request"]["model"] == "qwen2.5:14b"
    assert calls["request"]["messages"][0]["content"] == "Ответь одним словом: OK"


@pytest.mark.asyncio
async def test_generate_json_uses_ollama_schema_format(monkeypatch) -> None:
    from app.schemas import LLMProductCopy

    calls = {}
    output = LLMProductCopy(
        seo_title="Манометр DM 02",
        seo_description="Описание товара.",
        seo_queries=["манометр DM 02", "манометр Манотомь", "манометр"],
        commercial_block="Назначение уточняется по паспорту.",
    )

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def chat(self, **kwargs):
            calls["request"] = kwargs
            import json

            return SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(output.model_dump(), ensure_ascii=False))
            )

    fake_module = ModuleType("ollama")
    fake_module.AsyncClient = FakeAsyncClient
    fake_module.ResponseError = type("ResponseError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    client = LLMClient(Settings(ollama_model="qwen2.5:14b"))
    result = await client.generate_json("system rules", "product input")

    assert result["seo_title"] == "Манометр DM 02"
    assert calls["request"]["model"] == "qwen2.5:14b"
    assert calls["request"]["format"] == LLMProductCopy.model_json_schema()
    assert calls["request"]["messages"][0]["content"] == "system rules"
    assert calls["request"]["stream"] is False


@pytest.mark.asyncio
async def test_missing_ollama_package_returns_configuration_error(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "ollama", raising=False)
    monkeypatch.setitem(sys.modules, "ollama", None)
    with pytest.raises(LLMConfigurationError, match="пакет ollama"):
        await LLMClient(Settings()).test_connection()


@pytest.mark.asyncio
async def test_missing_model_returns_pull_instruction(monkeypatch) -> None:
    class FakeResponseError(Exception):
        status_code = 404

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def chat(self, **kwargs):
            raise FakeResponseError("model not found")

    fake_module = ModuleType("ollama")
    fake_module.AsyncClient = FakeAsyncClient
    fake_module.ResponseError = FakeResponseError
    monkeypatch.setitem(sys.modules, "ollama", fake_module)

    with pytest.raises(LLMClientError, match="ollama pull qwen2.5:14b"):
        await LLMClient(Settings(ollama_model="qwen2.5:14b")).test_connection()
