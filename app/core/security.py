from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)


class AuthenticatedUser(BaseModel):
    id: str
    roles: list[str] = []
    email: str | None = None
    username: str | None = None


class JWKSKeyManager:
    """Manages fetching, caching, and key rotation for Keycloak JWKS public keys."""

    def __init__(self, jwks_url: str) -> None:
        self.jwks_url = jwks_url
        self._keys: dict[str, dict[str, Any]] = {}

    async def _fetch_jwks(self) -> dict[str, dict[str, Any]]:
        urls = [self.jwks_url]
        if "keycloak:8080" in self.jwks_url:
            urls.append(self.jwks_url.replace("keycloak:8080", "localhost:8080"))

        last_error = None
        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                    new_keys = {k["kid"]: k for k in data.get("keys", []) if "kid" in k}
                    self._keys.update(new_keys)
                    return self._keys
            except Exception as e:
                last_error = e

        logger.warning("Could not fetch JWKS from %s: %s", urls, last_error)
        return self._keys

    async def get_key_for_token(self, token: str) -> dict[str, Any]:
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token header",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

        kid = unverified_header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token header missing key identifier ('kid')",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Check in-memory key cache first
        if kid in self._keys:
            return self._keys[kid]

        # Key rotation or cold start: fetch fresh JWKS
        await self._fetch_jwks()
        if kid in self._keys:
            return self._keys[kid]

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Public key not found for token 'kid'",
            headers={"WWW-Authenticate": "Bearer"},
        )


jwks_manager = JWKSKeyManager(settings.KEYCLOAK_JWKS_URL)


async def verify_token(token: str) -> AuthenticatedUser:
    """Strictly validates JWT signature, expiration, issuer, audience,
    and extracts user claims.
    """
    key = await jwks_manager.get_key_for_token(token)

    # Keycloak may be addressed via localhost (host network)
    # or keycloak:8080 (Docker network)
    valid_issuers = [settings.KEYCLOAK_ISSUER]
    if "localhost:8080" in settings.KEYCLOAK_ISSUER:
        valid_issuers.append(
            settings.KEYCLOAK_ISSUER.replace("localhost:8080", "keycloak:8080")
        )
    elif "keycloak:8080" in settings.KEYCLOAK_ISSUER:
        valid_issuers.append(
            settings.KEYCLOAK_ISSUER.replace("keycloak:8080", "localhost:8080")
        )

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.KEYCLOAK_AUDIENCE,
            issuer=valid_issuers,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iat": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iss": True,
            },
        )
    except ExpiredSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except JWTClaimsError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token claim validation failed: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject ('sub') claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    roles = payload.get("realm_access", {}).get("roles", [])
    if not isinstance(roles, list):
        roles = []

    return AuthenticatedUser(
        id=sub,
        roles=[str(r) for r in roles],
        email=payload.get("email"),
        username=payload.get("preferred_username"),
    )
