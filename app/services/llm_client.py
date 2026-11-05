from typing import Any

from app.config import Settings
from app.schemas import LLMProductCopy, SEODescriptionOutput


class LLMClientError(RuntimeError):
    """Raised when the local LLM request or response is invalid."""


class LLMConfigurationError(LLMClientError):
    """Raised when the Ollama client dependency is unavailable."""


class LLMClient:
    """Async client for a local Ollama server with schema-constrained JSON output."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _load_sdk() -> tuple[Any, type[Exception]]:
        try:
            from ollama import AsyncClient, ResponseError  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMConfigurationError(
                "Не установлен пакет ollama. Выполните: pip install -e ."
            ) from exc
        return AsyncClient, ResponseError

    def _create_client(self, async_client: Any) -> Any:
        return async_client(
            host=self.settings.ollama_base_url,
            timeout=self.settings.ollama_timeout_seconds,
        )

    def _raise_ollama_error(self, exc: Exception, response_error: type[Exception]) -> None:
        if isinstance(exc, response_error):
            status = getattr(exc, "status_code", None)
            detail = str(exc).strip().replace("\n", " ")[:300]
            if status == 404:
                raise LLMClientError(
                    f"Модель '{self.settings.ollama_model}' не найдена в Ollama. "
                    f"Выполните: ollama pull {self.settings.ollama_model}"
                ) from exc
            raise LLMClientError(
                f"Ollama вернул ошибку{f' (HTTP {status})' if status else ''}: {detail}"
            ) from exc

        # Ollama's Python SDK uses HTTPX exceptions underneath.
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is an SDK dependency
            httpx = None  # type: ignore[assignment]

        if httpx is not None and isinstance(exc, httpx.TimeoutException):
            raise LLMClientError(
                "Истекло время ожидания ответа Ollama. Увеличьте OLLAMA_TIMEOUT_SECONDS "
                "или выберите более лёгкую модель."
            ) from exc
        if isinstance(exc, (ConnectionError, OSError)) or (
            httpx is not None and isinstance(exc, httpx.ConnectError)
        ):
            raise LLMClientError(
                "Не удалось подключиться к Ollama. Убедитесь, что приложение Ollama "
                "запущено и сервер доступен по адресу "
                f"{self.settings.ollama_base_url}."
            ) from exc

        raise LLMClientError(f"Ошибка локальной модели Ollama: {exc}") from exc

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        async_client, response_error = self._load_sdk()
        client = self._create_client(async_client)

        try:
            async with client:
                response = await client.chat(
                    model=self.settings.ollama_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    format=LLMProductCopy.model_json_schema(),
                    options={
                        "temperature": 0.2,
                        "num_ctx": self.settings.ollama_num_ctx,
                        "num_predict": self.settings.ollama_num_predict,
                    },
                    stream=False,
                    keep_alive=self.settings.ollama_keep_alive,
                )
        except Exception as exc:
            self._raise_ollama_error(exc, response_error)
            raise  # Unreachable, keeps static type checkers satisfied.

        content = response.message.content
        try:
            parsed = LLMProductCopy.model_validate_json(content)
        except Exception as exc:
            raise LLMClientError(
                "Ollama вернул ответ, который не удалось разобрать как JSON "
                "по ожидаемой схеме. Повторите генерацию."
            ) from exc
        return parsed.model_dump()

    async def test_connection(self) -> str:
        """Send a short local inference request to verify the server and model."""
        async_client, response_error = self._load_sdk()
        client = self._create_client(async_client)

        try:
            async with client:
                response = await client.chat(
                    model=self.settings.ollama_model,
                    messages=[
                        {
                            "role": "user",
                            "content": "Ответь одним словом: OK",
                        }
                    ],
                    options={"temperature": 0, "num_predict": 16},
                    stream=False,
                    keep_alive=self.settings.ollama_keep_alive,
                )
        except Exception as exc:
            self._raise_ollama_error(exc, response_error)
            raise

        reply = (response.message.content or "").strip()
        if not reply:
            raise LLMClientError("Ollama доступен, но локальная модель вернула пустой ответ.")
        return reply


    async def repair_seo_description(self, system_prompt: str, user_prompt: str) -> str:
        """Repair only the SEO description using a dedicated one-field JSON schema."""
        async_client, response_error = self._load_sdk()
        client = self._create_client(async_client)

        try:
            async with client:
                response = await client.chat(
                    model=self.settings.ollama_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    format=SEODescriptionOutput.model_json_schema(),
                    options={
                        "temperature": 0.1,
                        "num_ctx": self.settings.ollama_num_ctx,
                        "num_predict": self.settings.ollama_num_predict,
                    },
                    stream=False,
                    keep_alive=self.settings.ollama_keep_alive,
                )
        except Exception as exc:
            self._raise_ollama_error(exc, response_error)
            raise

        try:
            parsed = SEODescriptionOutput.model_validate_json(response.message.content)
        except Exception as exc:
            raise LLMClientError(
                "Ollama вернул некорректный JSON при исправлении SEO-описания."
            ) from exc
        return parsed.seo_description.strip()
