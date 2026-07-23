from ipaddress import ip_address
from urllib.parse import SplitResult, urlsplit, urlunsplit


def _is_loopback(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validated_url(value: str, *, origin_only: bool) -> tuple[SplitResult, str, int | None]:
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise ValueError("absolute HTTP(S) URL required")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials are not allowed")
    if parsed.query or parsed.fragment:
        raise ValueError("query strings and fragments are not allowed")
    if origin_only and parsed.path not in {"", "/"}:
        raise ValueError("an origin cannot contain a path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid port") from exc
    return parsed, hostname, port


def _authority(scheme: str, hostname: str, port: int | None) -> str:
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    return rendered_host if port in {None, default_port} else f"{rendered_host}:{port}"


def normalize_base_url(value: str) -> str:
    parsed, hostname, port = _validated_url(value, origin_only=False)
    scheme = parsed.scheme.lower()
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, _authority(scheme, hostname, port), path, "", ""))


def base_url_origin(value: str) -> str:
    parsed, hostname, port = _validated_url(value, origin_only=False)
    scheme = parsed.scheme.lower()
    return f"{scheme}://{_authority(scheme, hostname, port)}"


def normalize_origin(value: str, *, allow_loopback_http: bool = True) -> str:
    parsed, hostname, port = _validated_url(value, origin_only=True)
    scheme = parsed.scheme.lower()
    if scheme == "http" and (not allow_loopback_http or not _is_loopback(hostname)):
        raise ValueError("HTTPS is required except for loopback development")
    return f"{scheme}://{_authority(scheme, hostname, port)}"


def frame_ancestors(origins: list[str]) -> str:
    sources = origins or ["https:", "http://localhost:*", "http://127.0.0.1:*"]
    return "frame-ancestors " + " ".join(sources)
