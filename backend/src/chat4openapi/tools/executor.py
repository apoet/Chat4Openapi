import asyncio
import json
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
import truststore

from chat4openapi.models import ApiSource, Tool
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.network_policy import UnsafeNetworkTarget, validate_network_target

NetworkValidator = Callable[[httpx.URL, bool], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RequestAuth:
    headers: Mapping[str, str] = field(default_factory=dict)
    cookies: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    status_code: int
    data: Any
    content_type: str


def _same_origin(left: httpx.URL, right: httpx.URL) -> bool:
    def origin(url: httpx.URL) -> tuple[str, str, int]:
        default_port = 443 if url.scheme == "https" else 80
        return url.scheme, url.host, url.port or default_port

    return origin(left) == origin(right)


class ToolExecutor:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        network_validator: NetworkValidator = validate_network_target,
        total_timeout: float = 60,
        max_redirects: int = 3,
        max_request_bytes: int = 1024 * 1024,
        max_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._transport = transport
        self._network_validator = network_validator
        self._total_timeout = total_timeout
        self._max_redirects = max_redirects
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    @staticmethod
    def _target_url(source: ApiSource, path: str, arguments: Mapping[str, Any]) -> httpx.URL:
        parsed_path = urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc:
            raise ToolExecutionError("invalid_target", "Tool paths must be relative to the API Source")
        for parameter in source_path_parameters(arguments):
            path = path.replace("{" + parameter + "}", quote(str(arguments[parameter]), safe=""))
        if "{" in path or "}" in path:
            raise ToolExecutionError("missing_argument", "A required path argument is missing")
        base = httpx.URL(source.base_url)
        base_path = base.path.rstrip("/")
        operation_path = f"/{path.lstrip('/')}"
        if base_path and (
            operation_path == base_path or operation_path.startswith(f"{base_path}/")
        ):
            combined_path = operation_path
        else:
            combined_path = f"{base_path}/{path.lstrip('/')}"
        return base.copy_with(path=combined_path, query=None)

    async def execute(
        self,
        tool: Tool,
        source: ApiSource,
        arguments: Mapping[str, Any],
        auth: RequestAuth,
    ) -> ToolExecutionResult:
        try:
            async with asyncio.timeout(self._total_timeout):
                return await self._execute(tool, source, arguments, auth)
        except TimeoutError as exc:
            raise ToolExecutionError("timeout", "Tool execution timed out") from exc
        except UnsafeNetworkTarget as exc:
            raise ToolExecutionError("unsafe_target", str(exc)) from exc
        except httpx.TimeoutException as exc:
            raise ToolExecutionError("timeout", "Upstream API request timed out") from exc
        except httpx.RequestError as exc:
            raise ToolExecutionError("upstream_unavailable", "Upstream API request failed") from exc

    async def _execute(
        self,
        tool: Tool,
        source: ApiSource,
        arguments: Mapping[str, Any],
        auth: RequestAuth,
    ) -> ToolExecutionResult:
        execution = tool.execution_schema
        method = str(execution["method"]).upper()
        path_arguments = {
            item["argument"]: arguments[item["argument"]]
            for item in execution.get("parameters", [])
            if item.get("in") == "path" and item.get("argument") in arguments
        }
        target = self._target_url(source, str(execution["path"]), path_arguments)
        source_url = httpx.URL(source.base_url)
        if not _same_origin(target, source_url):
            raise ToolExecutionError("invalid_target", "Tool target uses a different origin")

        query: dict[str, Any] = {}
        headers: dict[str, str] = {"User-Agent": "Agent4API/0.1"}
        cookies: dict[str, str] = {}
        for parameter in execution.get("parameters", []):
            argument = parameter.get("argument", parameter.get("name"))
            if argument not in arguments:
                if parameter.get("required"):
                    raise ToolExecutionError(
                        "missing_argument", f"Required argument '{argument}' is missing"
                    )
                continue
            location = parameter.get("in")
            name = parameter.get("name", argument)
            if location == "query":
                query[name] = arguments[argument]
            elif location == "header":
                headers[name] = str(arguments[argument])
            elif location == "cookie":
                cookies[name] = str(arguments[argument])
        query.update(auth.query)
        headers.update(auth.headers)
        cookies.update(auth.cookies)

        request_kwargs: dict[str, Any] = {}
        request_body = execution.get("request_body")
        if request_body:
            if "arguments" in request_body:
                body = {
                    name: arguments[name]
                    for name in request_body["arguments"]
                    if name in arguments
                }
            else:
                body = arguments.get(request_body.get("argument", "body"))
            content_type = request_body.get("content_type", "application/json")
            if content_type == "application/json" or content_type.endswith("+json"):
                request_kwargs["json"] = body
            elif content_type == "application/x-www-form-urlencoded":
                request_kwargs["data"] = body
            else:
                request_kwargs["content"] = body
                headers.setdefault("content-type", content_type)

        timeout = httpx.Timeout(30, connect=10)
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=timeout,
            follow_redirects=False,
            verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        ) as client:
            request = client.build_request(
                method, target, params=query, headers=headers, **request_kwargs
            )
            if cookies:
                httpx.Cookies(cookies).set_cookie_header(request)
            if len(request.content) > self._max_request_bytes:
                raise ToolExecutionError("request_too_large", "Tool request body is too large")
            response = await self._send_with_redirects(
                client, request, source_url, source.allow_private_networks
            )
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        raw = response.content
        if content_type == "application/json" or content_type.endswith("+json"):
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError:
                data = raw.decode(response.encoding or "utf-8", errors="replace")
        else:
            data = raw.decode(response.encoding or "utf-8", errors="replace")
        if not 200 <= response.status_code < 300:
            raise ToolExecutionError(
                "upstream_error",
                f"Upstream API returned HTTP {response.status_code}",
                status_code=response.status_code,
                details=data,
            )
        return ToolExecutionResult(response.status_code, data, content_type)

    async def _send_with_redirects(
        self,
        client: httpx.AsyncClient,
        request: httpx.Request,
        source_url: httpx.URL,
        allow_private_networks: bool,
    ) -> httpx.Response:
        for redirect_count in range(self._max_redirects + 1):
            await self._network_validator(request.url, allow_private_networks)
            response = await client.send(request, stream=True)
            if response.is_redirect:
                await response.aclose()
                if redirect_count >= self._max_redirects:
                    raise ToolExecutionError("too_many_redirects", "Upstream API redirected too many times")
                location = response.headers.get("location")
                if not location:
                    raise ToolExecutionError("invalid_redirect", "Upstream redirect has no location")
                redirected = request.url.join(location)
                if not _same_origin(redirected, source_url):
                    raise ToolExecutionError("invalid_redirect", "Redirect targets a different origin")
                request = client.build_request(
                    request.method,
                    redirected,
                    headers=request.headers,
                    content=request.content,
                )
                continue
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._max_response_bytes:
                    await response.aclose()
                    raise ToolExecutionError("response_too_large", "Upstream response is too large")
                chunks.append(chunk)
            await response.aclose()
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                request=request,
            )
        raise AssertionError("redirect loop exited unexpectedly")


def source_path_parameters(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(arguments)
