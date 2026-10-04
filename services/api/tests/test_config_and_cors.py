from fastapi.testclient import TestClient

from app.core.config import Settings


def test_supabase_urls_are_derived_from_the_project_url() -> None:
    settings = Settings(_env_file=None, supabase_url="https://abc.supabase.co/")
    assert settings.supabase_jwt_issuer == "https://abc.supabase.co/auth/v1"
    assert settings.supabase_jwks_url == "https://abc.supabase.co/auth/v1/.well-known/jwks.json"


def test_no_project_url_means_no_key_endpoint() -> None:
    settings = Settings(_env_file=None, supabase_url="")
    assert settings.supabase_jwks_url == ""
    assert settings.supabase_jwt_issuer == ""


def test_cors_origins_are_parsed_from_a_comma_separated_list() -> None:
    settings = Settings(_env_file=None, cors_origins=" http://localhost:3000/ ,https://a.test,, ")
    assert settings.cors_origin_list == ["http://localhost:3000", "https://a.test"]


def test_secrets_are_not_shown_when_settings_are_printed() -> None:
    settings = Settings(
        _env_file=None, supabase_service_role_key="super-secret", supabase_jwt_secret="jwt-secret"
    )
    assert "super-secret" not in repr(settings)
    assert "jwt-secret" not in repr(settings)


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/api/v1/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )


def test_allowed_origin_passes_cors_preflight(client: TestClient) -> None:
    response = _preflight(client, "http://localhost:3000")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_unknown_origin_fails_cors_preflight(client: TestClient) -> None:
    response = _preflight(client, "https://evil.example")
    assert "access-control-allow-origin" not in response.headers
