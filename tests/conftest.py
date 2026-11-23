from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jose import jwk, jwt

from app.core.config import settings
from app.core.security import jwks_manager
from app.db.session import engine
from app.main import app

# Generate static test RSA keypair for hermetic tests
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


@pytest.fixture(autouse=True)
def inject_test_jwks() -> None:
    jwks_manager._keys[_TEST_KID] = _TEST_JWK


@pytest.fixture(autouse=True)
async def cleanup_db_connections() -> AsyncGenerator[None, None]:
    yield
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
