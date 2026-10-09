"""Tests for the OpenAI vision provider."""

import json
from uuid import UUID

import httpx2
import pytest

from app.providers.openai import OpenAIVisionError, OpenAIVisionProvider

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


def openai_success_response(observations: list[str]) -> httpx2.Response:
    """Create a successful OpenAI response."""
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


def openai_error_response(status_code: int, message: str = "") -> httpx2.Response:
    """Create an OpenAI error response."""
    return httpx2.Response(
        status_code,
        json={"error": {"message": message, "type": "error"}},
    )


class TestOpenAIVisionProvider:
    """Tests for OpenAIVisionProvider implementation."""

    def test_has_describe_method(self) -> None:
        """Verify OpenAIVisionProvider has the required describe method."""
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        assert hasattr(provider, "describe")
        assert callable(provider.describe)
        provider.close()

    def test_missing_api_key_raises_error(self) -> None:
        """Missing API key should raise OpenAIVisionError at construction."""
        with pytest.raises(OpenAIVisionError, match="OpenAI API key is required"):
            OpenAIVisionProvider(
                api_key="",
                base_url="https://test.example.com",
                model="test-model",
            )

    def test_missing_document_url_returns_empty_structured(self) -> None:
        """Missing document_url should return empty structured dict without calling API."""
        provider = OpenAIVisionProvider(
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
        provider = OpenAIVisionProvider(
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
        # New structured format from model
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
            return openai_success_response(model_response)

        http, requests = recording(handler)
        provider = OpenAIVisionProvider(
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
        custom_base = "https://custom.openai.com/v1"
        custom_model = "gpt-4o"

        def handler(request: httpx2.Request) -> httpx2.Response:
            assert str(request.url).startswith(custom_base)
            body = json.loads(request.content)
            assert body["model"] == custom_model
            return openai_success_response([])

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url=custom_base,
            model=custom_model,
        )
        provider._client = http

        result = provider.describe(
            document_url=DOCUMENT_URL,
            text_hint="",
        )
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
            return openai_success_response([])

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
            return openai_success_response([])

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
            return openai_success_response([])

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
            return openai_success_response([])

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        provider.describe(document_url=DOCUMENT_URL, text_hint=hint)
        provider.close()

    def test_empty_model_response_handled_safely(self) -> None:
        """Empty model content should return empty structured dict."""

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
        provider = OpenAIVisionProvider(
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
        """Missing choices in response should raise OpenAIVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json={"choices": []})

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="No choices"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_missing_message_content_returns_empty(self) -> None:
        """Missing message content should return empty structured dict (graceful handling)."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={"choices": [{"message": {}, "finish_reason": "stop"}]},
            )

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
        """Invalid JSON response should raise OpenAIVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=b"not valid json")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="invalid response"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_model_returns_non_list_handled_safely(self) -> None:
        """Model returning non-list should return empty structured dict."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openai_success_response("not a list")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
            return openai_success_response(
                [
                    {"type": "object", "label": "valid", "certainty": "certain"},
                    123,
                    None,
                    "",
                    {"type": "object", "label": "also valid", "certainty": "certain"},
                ]
            )

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
            return openai_error_response(401, "Invalid API key")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="invalid-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="Invalid OpenAI API key"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_http_429_raises_rate_limit_error(self) -> None:
        """HTTP 429 should raise rate limit error."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openai_error_response(429, "Rate limit exceeded")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="rate limit"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_http_500_raises_error(self) -> None:
        """HTTP 500 should raise error."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            return openai_error_response(500, "Internal server error")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="HTTP 500"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_request_timeout_raises_error(self) -> None:
        """Request timeout should raise OpenAIVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.TimeoutException("Request timed out")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="timed out"):
            provider.describe(document_url=DOCUMENT_URL, text_hint="")
        provider.close()

    def test_network_error_raises_error(self) -> None:
        """Network error should raise OpenAIVisionError."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.NetworkError("Connection failed")

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        provider._client = http

        with pytest.raises(OpenAIVisionError, match="unavailable"):
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
        provider = OpenAIVisionProvider(
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
            return openai_success_response(
                [
                    {"type": "object", "label": long_obs, "certainty": "certain"},
                    {"type": "object", "label": short_obs, "certainty": "certain"},
                ]
            )

        http, _ = recording(handler)
        provider = OpenAIVisionProvider(
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
        provider = OpenAIVisionProvider(
            api_key="test-key",
            base_url="https://test.example.com",
            model="test-model",
        )
        with provider as p:
            assert p is provider
