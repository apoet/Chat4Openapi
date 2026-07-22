import pytest

from chat4openapi.embed.urls import frame_ancestors, normalize_base_url, normalize_origin


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Chat.Example.com/", "https://chat.example.com"),
        ("https://chat.example.com/app///", "https://chat.example.com/app"),
        ("https://chat.example.com:443", "https://chat.example.com"),
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
        ("http://localhost:8000/base/", "http://localhost:8000/base"),
    ],
)
def test_normalize_base_url(value: str, expected: str) -> None:
    assert normalize_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://chat.example.com",
        "https://user:password@chat.example.com",
        "https://chat.example.com?q=1",
        "https://chat.example.com#fragment",
        "ftp://chat.example.com",
        "chat.example.com",
        "https://chat.example.com:invalid",
    ],
)
def test_normalize_base_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_base_url(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Docs.Example/", "https://docs.example"),
        ("https://docs.example:443", "https://docs.example"),
        ("http://localhost:5173", "http://localhost:5173"),
        ("http://127.2.3.4:5173", "http://127.2.3.4:5173"),
        ("http://[::1]:5173", "http://[::1]:5173"),
    ],
)
def test_normalize_origin(value: str, expected: str) -> None:
    assert normalize_origin(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://docs.example",
        "https://docs.example/path",
        "https://docs.example?q=1",
        "https://user@docs.example",
    ],
)
def test_normalize_origin_rejects_non_origin_or_insecure_value(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_origin(value)


def test_frame_ancestors_uses_exact_configured_origins() -> None:
    assert frame_ancestors(["https://one.example", "https://two.example:8443"]) == (
        "frame-ancestors https://one.example https://two.example:8443"
    )


def test_frame_ancestors_empty_list_allows_secure_and_loopback_parents() -> None:
    assert frame_ancestors([]) == (
        "frame-ancestors https: http://localhost:* http://127.0.0.1:*"
    )
