import re
from typing import Any

from chat4openapi.models import ApiSourceToolAuthConfig, GlobalToolAuthConfig
from chat4openapi.tools.executor import RequestAuth

_PATH_PART = re.compile(r"(?:^|\.)([^.\[\]]+)|\[(\d+)\]")


class AuthMappingError(ValueError):
    pass


def extract_json_path(value: Any, path: str | None) -> Any:
    if not path:
        return None
    normalized = path[1:] if path.startswith("$") else path
    current = value
    matches = list(_PATH_PART.finditer(normalized))
    if not matches:
        raise AuthMappingError(f"Invalid JSON path: {path}")
    try:
        for match in matches:
            key, index = match.groups()
            current = current[int(index)] if index is not None else current[key]
    except (KeyError, IndexError, TypeError) as exc:
        raise AuthMappingError(f"Authentication response does not contain {path}") from exc
    return current


ToolAuthConfig = GlobalToolAuthConfig | ApiSourceToolAuthConfig


def _auth_value(config: ToolAuthConfig, payload: Any) -> str:
    token = extract_json_path(payload, config.token_json_path)
    if token is None:
        raise AuthMappingError("Authentication token is missing")
    prefix = (config.auth_prefix or "").strip()
    return f"{prefix} {token}" if prefix else str(token)


def build_request_auth(config: ToolAuthConfig, payload: Any) -> RequestAuth:
    value = _auth_value(config, payload)
    name = config.auth_name
    if config.auth_type == "bearer" or config.auth_type == "header":
        return RequestAuth(headers={name: value})
    if config.auth_type == "cookie":
        return RequestAuth(cookies={name: value})
    if config.auth_type == "query":
        return RequestAuth(query={name: value})
    raise AuthMappingError(f"Unsupported authentication type: {config.auth_type}")
