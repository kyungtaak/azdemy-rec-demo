import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.service import ServiceError


logger = logging.getLogger("azdemy.api")
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthSettings:
    tenant_id: str
    audience: str
    principal_learners: dict[str, str]

    @classmethod
    def from_environment(cls):
        tenant = str(UUID(os.environ["AZDEMY_TENANT_ID"]))
        audience = str(UUID(os.environ["AZDEMY_API_CLIENT_ID"]))
        mapping = json.loads(os.environ["AZDEMY_PRINCIPAL_LEARNERS"])
        if not isinstance(mapping, dict) or not mapping:
            raise ValueError("AZDEMY_PRINCIPAL_LEARNERS must be a nonempty object")
        if any(not isinstance(v, str) or not v for v in mapping.values()):
            raise ValueError("Principal mappings must use nonempty learner IDs")
        return cls(tenant, audience, {str(UUID(k)): v for k, v in mapping.items()})


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return AuthSettings.from_environment()


@lru_cache(maxsize=4)
def signing_keys(tenant_id: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
        timeout=10, cache_jwk_set=True, lifespan=300)


def validate_token(token: str, settings: AuthSettings) -> str:
    try:
        key = signing_keys(settings.tenant_id).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, key.key, algorithms=["RS256"], audience=settings.audience,
            issuer=f"https://login.microsoftonline.com/{settings.tenant_id}/v2.0",
            options={"require": ["exp", "iat", "iss", "aud", "tid", "oid"]})
    except jwt.PyJWKClientConnectionError as error:
        logger.error("Entra signing keys unavailable: %s", type(error).__name__)
        raise ServiceError(503, "SYSTEM_ERROR", "인증 키를 확인할 수 없습니다.") from error
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as error:
        logger.warning("Rejected token: %s", type(error).__name__)
        raise ServiceError(401, "UNAUTHORIZED", "유효한 Entra 액세스 토큰이 필요합니다.") from error
    if (claims["tid"] != settings.tenant_id or not isinstance(claims["oid"], str)
            or not claims["oid"]):
        raise ServiceError(401, "UNAUTHORIZED", "허용되지 않은 테넌트입니다.")
    scopes, roles = claims.get("scp", ""), claims.get("roles", [])
    allowed_scope = isinstance(scopes, str) and "access_as_user" in scopes.split()
    allowed_role = isinstance(roles, list) and "Learner.Read" in roles
    if not (allowed_scope or allowed_role):
        raise ServiceError(403, "FORBIDDEN", "교육 조회 권한이 없습니다.")
    learner_id = settings.principal_learners.get(claims["oid"])
    if learner_id is None:
        raise ServiceError(403, "FORBIDDEN", "이 데모에 허용된 호출 주체가 아닙니다.")
    return learner_id


def authenticated_learner_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: AuthSettings = Depends(get_auth_settings),
) -> str:
    if credentials is None:
        raise ServiceError(401, "UNAUTHORIZED", "Entra Bearer 토큰이 필요합니다.")
    return validate_token(credentials.credentials, settings)
