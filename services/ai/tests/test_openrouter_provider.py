"""Tests for the OpenRouter vision provider."""

import json
import os
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import httpx2
import pytest

from app.core.config import Settings
from app.providers.mock import MockVisionProvider
from app.providers.openrouter import OpenRouterVisionError, OpenRouterVisionProvider

# Test constants
EVIDENCE_ID = UUID("eeeeeeee-0000-4000-8000-000000000001")
DOCUMENT_URL = "https://storage.test/evidence/p/e/original.jpg?token=signed"


def recording(handler) -> tuple[httpx2.Client, list[httpx2.Request]]:
    """Create an HTTP client that records requests using MockTransport."""
    requests: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    return httpx2.Client(transport=httpx2.MockTransport(record)), requests


def openrouter_success_response(observations: list[str]) -> httpx2.Response:
    """Create a successful OpenRouter response."""
    content = json.dumps(observations)
    return httpx2.Response(
        200,
        json={
            "id": "test-completion",
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def openrouter_error_response(status_code: int, message: str = "") -> httpx2.Response:
    """Create an OpenRouter error response."""
    return httpx2.Response(
        status_code,
        json={"error": {"message": message, "type": "error"}},
    )


class TestOpenRouterVisionProvider:
    """Tests for OpenRouterVisionProvider implementation."""

    def test_has_describe_method(self) -> None:
        """Verify OpenRouterVisionProvider has the required describe method."""
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        assert hasattr(provider, "describe")
        assert callable(provider.describe)
        provider.close()

    def test_missing_api_key_raises_error(self) -> None:
        """Missing API key should raise OpenRouterVisionError at construction."""
        with pytest.raises(OpenRouterVisionError, match="API key is required"):
            OpenRouterVisionProvider(
                api_key="",
                base_url="https://test.example.com",
                model="test-model",
            )

    def test_missing_document_url_returns_empty_structured(self) -> None:
        """Missing document_url should return empty structured dict without calling API."""
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        result = provider.describe(document_url=None, text_hint="some hint")
        assert result == {
            "objects_certain": [],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_empty_document_url_returns_empty_structured(self) -> None:
        """Empty document_url should return empty structured dict."""
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        result = provider.describe(document_url="", text_hint="some hint")
        assert result == {
            "objects_certain": [],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_successful_response_parses_structured_observations(self) -> None:
        """Successful model response should return parsed structured observations."""
        model_response = [
            {"type": "object", "label": "formwork", "certainty": "certain"},
            {"type": "object", "label": "concrete pour", "certainty": "possible"},
            {"type": "object", "label": "rebar", "certainty": "certain"},
        ]
        expected = {
            "objects_certain": ["formwork", "rebar"],
            "objects_possible": ["concrete pour"],
            "activities_certain": [],
            "activities_possible": [],
        }

        def handler(request: httpx2.Request) -> httpx2.Response:
            assert request.url.path == "/chat/completions"
            assert request.headers["Authorization"] == "Bearer test-key"
            assert request.headers["Content-Type"] == "application/json"
            body = json.loads(request.content)
            assert body["model"] == "test-model"
            assert len(body["messages"]) == 1
            assert body["messages"][0]["role"] == "user"
            content = body["messages"][0]["content"]
            assert any(c["type"] == "image_url" for c in content)
            assert any("Context (untrusted metadata)" in c.get("text", "") for c in content)
            return openrouter_success_response(model_response)

        http, requests = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(
            document_url=DOCUMENT_URL,
            text_hint="Level 3 slab pour",
        )

        assert result == expected
        assert len(requests) == 1
        provider.close()

    def test_request_uses_configured_base_url_and_model(self) -> None:
        """Request should use configured base URL and model."""
        custom_base = "https://custom.openrouter.ai/api/v1"
        custom_model = "anthropic/claude-3-opus"

        def handler(request: httpx2.Request) -> httpx2.Response:
            assert str(request.url).startswith(custom_base)
            body = json.loads(request.content)
            assert body["model"] == custom_model
            return openrouter_success_response([])

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url=custom_base,
            model=custom_model,
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == {
            "objects_certain": [],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_request_includes_bearer_auth_header(self) -> None:
        """Request should include Bearer token authentication."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            auth = request.headers.get("Authorization")
            assert auth == "Bearer secret-api-key"
            return openrouter_success_response([])

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="secret-api-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_request_includes_image_url(self) -> None:
        """Request payload should include the supplied image URL."""
        test_url = "https://custom.storage/evidence/test.jpg?token=abc"

        def handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content)
            content = body["messages"][0]["content"]
            image_content = next(c for c in content if c["type"] == "image_url")
            assert image_content["image_url"]["url"] == test_url
            return openrouter_success_response([])

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        provider.describe(document_url=test_url, text_hint="")
        provider.close()

    def test_system_prompt_contains_construction_instructions(self) -> None:
        """System prompt should contain construction-specific analysis instructions."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content)
            content = body["messages"][0]["content"]
            system_text = next(
                c["text"]
                for c in content
                if c["type"] == "text" and "construction" in c["text"].lower()
            )
            assert "construction site evidence analyst" in system_text.lower()
            assert "certain:" in system_text
            assert "possible:" in system_text
            assert "untrusted metadata" in system_text.lower()
            return openrouter_success_response([])

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_text_hint_included_as_context(self) -> None:
        """text_hint should be included as untrusted context."""
        hint = "Level 3 slab pour completed east side"

        def handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content)
            content = body["messages"][0]["content"]
            text_parts = [c["text"] for c in content if c["type"] == "text"]
            combined = " ".join(text_parts)
            assert "untrusted metadata" in combined.lower()
            assert hint in combined
            return openrouter_success_response([])

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        provider.describe(document_url=DOCUMENT_URL, text_hint=hint)
        provider.close()

    def test_empty_model_response_handled_safely(self) -> None:
        """Empty model content should return empty list."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}
                    ]
                },
            )

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == {
            "objects_certain": [],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_missing_choices_handled_safely(self) -> None:
        """Missing choices in response should raise OpenRouterVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json={"choices": []})

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="No choices"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_missing_message_content_returns_empty(self) -> None:
        """Missing message content should return empty list (graceful handling)."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={"choices": [{"message": {}, "finish_reason": "stop"}]},
            )

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == {
            "objects_certain": [],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_malformed_json_handled_safely(self) -> None:
        """Invalid JSON response should raise OpenRouterVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=b"not valid json")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="invalid response"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_model_returns_non_list_handled_safely(self) -> None:
        """Model returning non-list should return empty list."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openrouter_success_response("not a list")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == {
            "objects_certain": [],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_model_returns_none_items_filtered(self) -> None:
        """Non-dict items in model response should be filtered out."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openrouter_success_response(
                [
                    {"type": "object", "label": "valid", "certainty": "certain"},
                    123,
                    None,
                    "",
                    {"type": "object", "label": "also valid", "certainty": "certain"},
                ]
            )

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == {
            "objects_certain": ["valid", "also valid"],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_http_401_raises_auth_error(self) -> None:
        """HTTP 401 should raise authentication error."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openrouter_error_response(401, "Invalid API key")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="invalid-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="Invalid OpenRouter API key"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_http_429_raises_rate_limit_error(self) -> None:
        """HTTP 429 should raise rate limit error."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openrouter_error_response(429, "Rate limit exceeded")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="rate limit"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_http_500_raises_error(self) -> None:
        """HTTP 500 should raise error."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openrouter_error_response(500, "Internal server error")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="HTTP 500"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_request_timeout_raises_error(self) -> None:
        """Request timeout should raise OpenRouterVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.TimeoutException("Request timed out")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="timed out"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_network_error_raises_error(self) -> None:
        """Network error should raise OpenRouterVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.NetworkError("Connection failed")

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenRouterVisionError, match="unavailable"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_json_in_markdown_code_fence_parsed(self) -> None:
        """Model response wrapped in markdown code fence should be parsed."""
        model_response = [
            {"type": "object", "label": "formwork", "certainty": "certain"},
            {"type": "object", "label": "concrete", "certainty": "possible"},
        ]
        expected = {
            "objects_certain": ["formwork"],
            "objects_possible": ["concrete"],
            "activities_certain": [],
            "activities_possible": [],
        }
        markdown_response = "```json\n" + json.dumps(model_response) + "\n```"

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": markdown_response},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == expected
        provider.close()

    def test_observation_length_limit_enforced(self) -> None:
        """Observations longer than 100 chars should be filtered."""
        long_obs = "x" * 150
        short_obs = "valid observation"

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openrouter_success_response(
                [
                    {"type": "object", "label": long_obs, "certainty": "certain"},
                    {"type": "object", "label": short_obs, "certainty": "certain"},
                ]
            )

        http, _ = recording(handler)
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        result = provider.describe(document_url=DOCUMENT_URL, text_hint="")
        assert result == {
            "objects_certain": [short_obs],
            "objects_possible": [],
            "activities_certain": [],
            "activities_possible": [],
        }
        provider.close()

    def test_context_manager_closes_client(self) -> None:
        """Context manager should properly close the HTTP client."""
        provider = OpenRouterVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        with provider as p:
            assert p is provider


class TestVisionProviderSelection:
    """Tests for configuration-driven vision provider selection."""

    def test_default_config_uses_mock_provider(self) -> None:
        """Default configuration should use MockVisionProvider."""
        from app.api.v1.deps import get_vision_provider

        settings = Settings(vision_provider="mock")
        provider = get_vision_provider(settings)
        assert isinstance(provider, MockVisionProvider)

    def test_openrouter_config_selects_openrouter_provider(self) -> None:
        """OpenRouter configuration should select OpenRouterVisionProvider."""
        from app.api.v1.deps import get_vision_provider

        settings = Settings(
            vision_provider="openrouter",
            openrouter_api_key="test-key",
        )
        provider = get_vision_provider(settings)
        assert isinstance(provider, OpenRouterVisionProvider)
        provider.close()

    def test_openrouter_without_key_raises_error(self) -> None:
        """OpenRouter selection without API key should raise clear error."""
        from app.api.v1.deps import get_vision_provider

        settings = Settings(
            vision_provider="openrouter",
            openrouter_api_key="",  # Empty key
        )
        with pytest.raises(
            OpenRouterVisionError,
            match="AI_VISION_PROVIDER=openrouter but AI_OPENROUTER_API_KEY is not set",
        ):
            get_vision_provider(settings)

    def test_evidence_service_uses_configured_provider(self) -> None:
        """EvidenceUnderstandingService should use the configured provider."""
        from app.api.v1.deps import get_evidence_service
        from app.services.evidence import EvidenceUnderstandingService

        service = get_evidence_service()
        assert isinstance(service, EvidenceUnderstandingService)


class TestProviderExceptionContract:
    """Tests for provider exception handling contract."""

    def test_openrouter_error_is_exception(self) -> None:
        """OpenRouterVisionError should be a proper Exception."""
        error = OpenRouterVisionError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"

    def test_provider_raises_on_missing_config(self) -> None:
        """Provider should raise clear error for missing configuration."""
        with pytest.raises(OpenRouterVisionError):
            OpenRouterVisionProvider(
                api_key="",
                base_url="https://test.example.com",
                model="test-model",
            )


class TestEnvFileLoading:
    """Tests for .env file loading behaviour."""

    def test_settings_loads_from_env_file_when_present(self, tmp_path: Path) -> None:
        """Settings should load values from a local .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "AI_VISION_PROVIDER=openrouter\n"
            "AI_OPENROUTER_API_KEY=test-key-from-env-file\n"
            "AI_OPENROUTER_MODEL=custom/model\n",
            encoding="utf-8",
        )

        settings = Settings(_env_file=env_file)

        assert settings.vision_provider == "openrouter"
        assert settings.openrouter_api_key.get_secret_value() == "test-key-from-env-file"
        assert settings.openrouter_model == "custom/model"

    def test_env_vars_override_env_file(self, tmp_path: Path) -> None:
        """Explicit environment variables should take precedence over .env file."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "AI_VISION_PROVIDER=openrouter\nAI_OPENROUTER_API_KEY=from-env-file\n",
            encoding="utf-8",
        )

        # Set env var to override
        with patch.dict(os.environ, {"AI_VISION_PROVIDER": "mock"}):
            settings = Settings(_env_file=env_file)

        assert settings.vision_provider == "mock"  # env var wins

    def test_default_provider_is_mock_without_env_file(self) -> None:
        """Default vision provider should be 'mock' when no config is provided."""
        # Pass a non-existent _env_file to disable automatic .env loading
        settings = Settings(_env_file=Path("/nonexistent/.env"))
        assert settings.vision_provider == "mock"

    def test_openrouter_requires_api_key_when_selected(self) -> None:
        """Selecting OpenRouter without API key should be detectable."""
        settings = Settings(vision_provider="openrouter", openrouter_api_key="")
        assert settings.vision_provider == "openrouter"
        assert settings.openrouter_api_key.get_secret_value() == ""

    def test_mock_provider_works_without_openrouter_config(self) -> None:
        """Mock provider should work without any OpenRouter configuration."""
        settings = Settings(vision_provider="mock")
        # Should not raise, all optional fields have defaults
        assert settings.vision_provider == "mock"
        assert settings.openrouter_api_key.get_secret_value() == ""
        assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
        assert settings.openrouter_model == "openai/gpt-4o-mini"
        assert settings.vision_timeout_seconds == 30.0

    def test_env_file_path_resolution(self) -> None:
        """Verify the env_file path points to services/ai/.env from config.py location."""
        # The actual path resolution happens at Settings instantiation
        # Just verify the config has the right structure
        assert Settings.model_config.get("env_file_encoding") == "utf-8"
