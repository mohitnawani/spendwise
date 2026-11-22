from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from jose import jwk, jwt

from app.core.config import settings
from app.core.security import jwks_manager

# Generate a static test RSA keypair for fast, hermetic unit tests
_TEST_KID = "spendwise-test-key-id"
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")
_PUBLIC_PEM = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode("utf-8")
)

_TEST_JWK: dict[str, Any] = jwk.RSAKey(key=_PUBLIC_PEM, algorithm="RS256").to_dict()
_TEST_JWK["kid"] = _TEST_KID


@pytest.fixture(autouse=True)
def inject_test_jwks() -> None:
    """Pre-seed the JWKS manager cache with our test public key."""
    jwks_manager._keys[_TEST_KID] = _TEST_JWK


def create_token(
    sub: str | None = None,
    roles: list[str] | None = None,
    exp: int | None = None,
    iss: str | None = None,
    aud: str | list[str] | None = None,
    kid: str | None = _TEST_KID,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub or f"user_{uuid.uuid4().hex[:8]}",
        "iss": iss or settings.KEYCLOAK_ISSUER,
        "aud": aud or settings.KEYCLOAK_AUDIENCE,
        "exp": exp or (now + 3600),
        "iat": now,
        "nbf": now,
        "realm_access": {"roles": roles if roles is not None else ["USER"]},
        "email": "test@spendwise.local",
        "preferred_username": "tester",
    }
    headers = {"kid": kid} if kid else {}
    return str(jwt.encode(payload, _PRIVATE_PEM, algorithm="RS256", headers=headers))


@pytest.mark.asyncio
async def test_missing_token_returns_401(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "Missing Authorization header" in response.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_scheme_returns_401(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Basic 12345"},
    )
    assert response.status_code == 401
    assert "Bearer token required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_malformed_token_returns_401(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(client: AsyncClient) -> None:
    expired_token = create_token(exp=int(time.time()) - 300)
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wrong_issuer_returns_401(client: AsyncClient) -> None:
    bad_iss_token = create_token(iss="http://malicious-issuer.com")
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bad_iss_token}"},
    )
    assert response.status_code == 401
    assert "claim validation failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_wrong_audience_returns_401(client: AsyncClient) -> None:
    bad_aud_token = create_token(aud="wrong-audience-app")
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bad_aud_token}"},
    )
    assert response.status_code == 401
    assert "claim validation failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_kid_header_returns_401(client: AsyncClient) -> None:
    token = create_token(kid=None)
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert "missing key identifier" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_valid_user_can_access_user_route(client: AsyncClient) -> None:
    token = create_token(roles=["USER"])
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "sub" in data
    assert "USER" in data["roles"]


@pytest.mark.asyncio
async def test_user_cannot_access_admin_route_returns_403(client: AsyncClient) -> None:
    token = create_token(roles=["USER"])
    response = await client.get(
        "/api/v1/auth/admin",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "ADMIN" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_can_access_admin_route(client: AsyncClient) -> None:
    token = create_token(roles=["ADMIN", "USER"])
    response = await client.get(
        "/api/v1/auth/admin",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Admin access granted"
    assert "ADMIN" in data["roles"]


@pytest.mark.asyncio
async def test_live_keycloak_tokens(client: AsyncClient) -> None:
    """Test using live Keycloak tokens if Keycloak is reachable."""
    user_token = None
    admin_token = None

    for base_url in ["http://keycloak:8080", "http://localhost:8080"]:
        try:
            async with httpx.AsyncClient(timeout=3.0) as kc:
                user_token_resp = await kc.post(
                    f"{base_url}/realms/spendwise/protocol/openid-connect/token",
                    data={
                        "client_id": "spendwise-api",
                        "username": "testuser",
                        "password": "testuser123",
                        "grant_type": "password",
                    },
                )
                if user_token_resp.status_code == 200:
                    user_token = user_token_resp.json()["access_token"]

                    admin_token_resp = await kc.post(
                        f"{base_url}/realms/spendwise/protocol/openid-connect/token",
                        data={
                            "client_id": "spendwise-api",
                            "username": "adminuser",
                            "password": "adminuser123",
                            "grant_type": "password",
                        },
                    )
                    if admin_token_resp.status_code == 200:
                        admin_token = admin_token_resp.json()["access_token"]
                        break
        except Exception:
            continue

    if not user_token or not admin_token:
        pytest.skip("Keycloak server not accessible or test users missing")

    # Test user token on /me
    resp_me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp_me.status_code == 200
    assert "USER" in resp_me.json()["roles"]

    # Test user token on /admin (must be 403)
    resp_admin_forbidden = await client.get(
        "/api/v1/auth/admin",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp_admin_forbidden.status_code == 403

    # Test admin token on /admin (must be 200)
    resp_admin = await client.get(
        "/api/v1/auth/admin",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_admin.status_code == 200
    assert "ADMIN" in resp_admin.json()["roles"]
