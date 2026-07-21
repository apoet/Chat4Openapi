import asyncio
import json
import socket

import httpx
import pytest

from chat4openapi.models import ApiSource, Tool
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.executor import RequestAuth, ToolExecutor
from chat4openapi.tools.network_policy import UnsafeNetworkTarget, validate_network_target


def source(*, allow_private_networks: bool = False) -> ApiSource:
    return ApiSource(
        name="Pet API",
        source_type="openapi",
        base_url="https://api.example.test/v1",
        allow_private_networks=allow_private_networks,
    )


def tool(execution_schema: dict | None = None) -> Tool:
    return Tool(
        api_source_id=1,
        operation_key="POST /pets/{pet_id}",
        name="create_pet",
        input_schema={"type": "object"},
        execution_schema=execution_schema
        or {
            "method": "POST",
            "path": "/pets/{pet_id}",
            "parameters": [
                {"name": "pet_id", "argument": "pet_id", "in": "path", "required": True},
                {"name": "trace", "argument": "trace", "in": "query", "required": False},
                {"name": "X-Mode", "argument": "mode", "in": "header", "required": False},
                {"name": "region", "argument": "region", "in": "cookie", "required": False},
            ],
            "request_body": {
                "content_type": "application/json",
                "arguments": ["name", "age"],
            },
        },
    )


async def allow_network(_url: httpx.URL, _allow_private: bool) -> None:
    return None


def test_does_not_duplicate_an_overlapping_base_path() -> None:
    api_source = source()
    api_source.base_url = "https://api.example.test/admin-api"

    target = ToolExecutor._target_url(api_source, "/admin-api/pets/{pet_id}", {"pet_id": 7})

    assert target == "https://api.example.test/admin-api/pets/7"


@pytest.mark.asyncio
async def test_places_arguments_and_request_scoped_auth() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.test/v1/pets/a%2Fb?trace=t&api_key=secret"
        assert request.headers["User-Agent"] == "Chat4Openapi/0.1"
        assert request.headers["X-Mode"] == "safe"
        assert request.headers["Authorization"] == "Bearer token"
        assert request.headers["Cookie"] in {"region=eu; sid=session", "sid=session; region=eu"}
        assert json.loads(request.content) == {"name": "Milo", "age": 3}
        return httpx.Response(200, json={"id": 7})

    executor = ToolExecutor(
        transport=httpx.MockTransport(handler), network_validator=allow_network
    )
    result = await executor.execute(
        tool(),
        source(),
        {"pet_id": "a/b", "trace": "t", "mode": "safe", "region": "eu", "name": "Milo", "age": 3},
        RequestAuth(
            headers={"Authorization": "Bearer token"},
            cookies={"sid": "session"},
            query={"api_key": "secret"},
        ),
    )

    assert result.status_code == 200
    assert result.data == {"id": 7}


@pytest.mark.asyncio
async def test_rejects_absolute_paths_and_cross_origin_redirects() -> None:
    executor = ToolExecutor(
        transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        network_validator=allow_network,
    )
    malicious = tool({"method": "GET", "path": "https://evil.test/data", "parameters": []})
    with pytest.raises(ToolExecutionError, match="relative"):
        await executor.execute(malicious, source(), {}, RequestAuth())

    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://evil.test/data"})

    redirecting = ToolExecutor(
        transport=httpx.MockTransport(redirect), network_validator=allow_network
    )
    with pytest.raises(ToolExecutionError, match="different origin"):
        await redirecting.execute(
            tool({"method": "GET", "path": "/pets", "parameters": []}),
            source(),
            {},
            RequestAuth(),
        )


@pytest.mark.asyncio
async def test_enforces_redirect_timeout_and_size_limits() -> None:
    def endless_redirect(request: httpx.Request) -> httpx.Response:
        count = int(request.url.params.get("n", "0"))
        return httpx.Response(302, headers={"Location": f"/v1/pets?n={count + 1}"})

    executor = ToolExecutor(
        transport=httpx.MockTransport(endless_redirect),
        network_validator=allow_network,
        max_redirects=3,
    )
    with pytest.raises(ToolExecutionError) as redirects:
        await executor.execute(
            tool({"method": "GET", "path": "/pets", "parameters": []}),
            source(),
            {},
            RequestAuth(),
        )
    assert redirects.value.code == "too_many_redirects"

    async def slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200)

    timeout_executor = ToolExecutor(
        transport=httpx.MockTransport(slow),
        network_validator=allow_network,
        total_timeout=0.01,
    )
    with pytest.raises(ToolExecutionError) as timeout:
        await timeout_executor.execute(
            tool({"method": "GET", "path": "/pets", "parameters": []}),
            source(),
            {},
            RequestAuth(),
        )
    assert timeout.value.code == "timeout"

    large_response = ToolExecutor(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 33)),
        network_validator=allow_network,
        max_response_bytes=32,
    )
    with pytest.raises(ToolExecutionError) as response_error:
        await large_response.execute(
            tool({"method": "GET", "path": "/pets", "parameters": []}),
            source(),
            {},
            RequestAuth(),
        )
    assert response_error.value.code == "response_too_large"


@pytest.mark.asyncio
async def test_returns_text_and_raises_structured_upstream_errors() -> None:
    text_executor = ToolExecutor(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="ready", headers={"content-type": "text/plain"})
        ),
        network_validator=allow_network,
    )
    result = await text_executor.execute(
        tool({"method": "GET", "path": "/health", "parameters": []}),
        source(),
        {},
        RequestAuth(),
    )
    assert result.data == "ready"

    error_executor = ToolExecutor(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(422, json={"error": "invalid pet"})
        ),
        network_validator=allow_network,
    )
    with pytest.raises(ToolExecutionError) as upstream:
        await error_executor.execute(
            tool({"method": "GET", "path": "/pets", "parameters": []}),
            source(),
            {},
            RequestAuth(),
        )
    assert upstream.value.code == "upstream_error"
    assert upstream.value.status_code == 422
    assert upstream.value.details == {"error": "invalid pet"}


@pytest.mark.asyncio
async def test_network_policy_rejects_private_addresses() -> None:
    def private_resolver(*_args):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    with pytest.raises(UnsafeNetworkTarget):
        await validate_network_target(
            httpx.URL("https://internal.test"),
            allow_private_networks=False,
            resolver=private_resolver,
        )

    await validate_network_target(
        httpx.URL("https://internal.test"),
        allow_private_networks=True,
        resolver=private_resolver,
    )
