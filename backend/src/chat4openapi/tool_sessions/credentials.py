import base64
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from string import ascii_letters, digits
from typing import Any

from chat4openapi.models import (
    ApiSource,
    ApiSourceToolAuthConfig,
    GlobalToolAuthConfig,
)
from chat4openapi.tools.executor import RequestAuth

FORBIDDEN_HEADERS = {
    "connection",
    "content-length",
    "cookie",
    "forwarded",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "via",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
}
COOKIE_NAME_CHARACTERS = frozenset(ascii_letters + digits + "!#$%&'*+-.^_`|~")


class CredentialValidationError(ValueError):
    def __init__(self, code: str = "tool_credentials.field_not_allowed") -> None:
        super().__init__(code)
        self.code = code


def _configured_names(source: ApiSource) -> tuple[dict[str, str], dict[str, str]]:
    headers: dict[str, str] = {}
    cookies: dict[str, str] = {}
    if not source.spec_snapshot:
        return headers, cookies
    try:
        spec = json.loads(source.spec_snapshot)
    except (TypeError, json.JSONDecodeError):
        return headers, cookies
    if not isinstance(spec, dict):
        return headers, cookies

    extension = spec.get("x-chat4openapi-credential-allowlist", {})
    if isinstance(extension, dict):
        for name in extension.get("headers", []):
            if isinstance(name, str) and name.strip():
                headers[name.lower()] = name
        for name in extension.get("cookies", []):
            if isinstance(name, str) and name.strip():
                cookies[name.lower()] = name

    components = spec.get("components", {})
    schemes = components.get("securitySchemes", {}) if isinstance(components, dict) else {}
    if not isinstance(schemes, dict):
        schemes = {}
    swagger_schemes = spec.get("securityDefinitions", {})
    if isinstance(swagger_schemes, dict):
        schemes = {**swagger_schemes, **schemes}
    for scheme in schemes.values():
        if not isinstance(scheme, dict):
            continue
        scheme_type = str(scheme.get("type", "")).lower()
        if scheme_type == "http" and str(scheme.get("scheme", "")).lower() == "bearer":
            headers["authorization"] = "Authorization"
        elif scheme_type == "apikey":
            name = scheme.get("name")
            location = str(scheme.get("in", "")).lower()
            if not isinstance(name, str) or not name.strip():
                continue
            if location == "header":
                headers[name.lower()] = name
            elif location == "cookie":
                cookies[name.lower()] = name
    return headers, cookies


def configured_credential_names(
    source: ApiSource,
    legacy_config: GlobalToolAuthConfig | ApiSourceToolAuthConfig | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    headers, cookies = _configured_names(source)
    if legacy_config is not None and legacy_config.enabled:
        name = legacy_config.auth_name
        if legacy_config.auth_type in {"bearer", "header"}:
            headers.setdefault(name.lower(), name)
        elif legacy_config.auth_type == "cookie":
            cookies.setdefault(name.lower(), name)
    return headers, cookies


def _normalize_fields(
    configured: Mapping[str, str], supplied: Mapping[str, str], *, headers: bool
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, value in supplied.items():
        if not isinstance(raw_name, str):
            raise CredentialValidationError()
        name = raw_name.strip().lower()
        invalid_cookie_value = not headers and isinstance(value, str) and (
            not value
            or any(
                not (
                    ordinal == 0x21
                    or 0x23 <= ordinal <= 0x2B
                    or 0x2D <= ordinal <= 0x3A
                    or 0x3C <= ordinal <= 0x5B
                    or 0x5D <= ordinal <= 0x7E
                )
                for ordinal in map(ord, value)
            )
        )
        invalid_cookie_name = not headers and (
            not set(raw_name) <= COOKIE_NAME_CHARACTERS
            or not set(configured.get(name, "")) <= COOKIE_NAME_CHARACTERS
        )
        if (
            not name
            or not isinstance(value, str)
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or invalid_cookie_value
            or invalid_cookie_name
            or (headers and (name in FORBIDDEN_HEADERS or name.startswith("x-forwarded-")))
            or name not in configured
            or configured[name] in normalized
        ):
            raise CredentialValidationError()
        normalized[configured[name]] = value
    return normalized


def validate_and_normalize_credentials(
    source: ApiSource,
    supplied: Mapping[str, Any],
    legacy_config: GlobalToolAuthConfig | ApiSourceToolAuthConfig | None = None,
) -> RequestAuth:
    unknown = set(supplied) - {"headers", "cookies"}
    headers = supplied.get("headers", {})
    cookies = supplied.get("cookies", {})
    if (
        unknown
        or not isinstance(headers, Mapping)
        or not isinstance(cookies, Mapping)
        or (not headers and not cookies)
    ):
        raise CredentialValidationError()
    configured_headers, configured_cookies = configured_credential_names(source, legacy_config)
    return RequestAuth(
        headers=_normalize_fields(configured_headers, headers, headers=True),
        cookies=_normalize_fields(configured_cookies, cookies, headers=False),
    )


def jwt_expiry(value: str) -> datetime | None:
    scheme, separator, candidate = value.partition(" ")
    token = candidate.strip() if separator and scheme.lower() == "bearer" else value.strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = payload.get("exp")
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            return None
        return datetime.fromtimestamp(float(exp), UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError, OSError, json.JSONDecodeError):
        return None


def credential_expiry(auth: RequestAuth) -> datetime | None:
    expiries = [
        expiry
        for value in (*auth.headers.values(), *auth.cookies.values())
        if (expiry := jwt_expiry(value)) is not None
    ]
    return min(expiries) if expiries else None


def auth_to_json(auth: RequestAuth) -> dict[str, dict[str, str]]:
    return {"headers": dict(auth.headers), "cookies": dict(auth.cookies)}


def auth_from_json(value: Mapping[str, Any]) -> RequestAuth:
    return RequestAuth(
        headers=dict(value.get("headers", {})), cookies=dict(value.get("cookies", {}))
    )
