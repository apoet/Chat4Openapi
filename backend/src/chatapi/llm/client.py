import json
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class CanonicalMessage:
    role: str
    content: Any
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CanonicalToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CanonicalResponse:
    content: str
    tool_calls: list[CanonicalToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class LlmProviderError(RuntimeError):
    def __init__(self, status_code: int, details: Any) -> None:
        super().__init__(f"LLM provider returned HTTP {status_code}")
        self.status_code = status_code
        self.details = details


class LlmClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def complete(
        self,
        *,
        provider_type: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[CanonicalMessage],
        tools: list[CanonicalTool] | None = None,
        max_tokens: int = 2048,
        temperature: float | None = None,
    ) -> CanonicalResponse:
        if provider_type == "openai":
            return await self._complete_openai(
                base_url, api_key, model, messages, tools or [], max_tokens, temperature
            )
        if provider_type == "anthropic":
            return await self._complete_anthropic(
                base_url, api_key, model, messages, tools or [], max_tokens, temperature
            )
        raise ValueError(f"Unsupported LLM provider type: {provider_type}")

    async def _post(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(60, connect=10),
        ) as client:
            response = await client.post(url, headers=headers, json=payload)
        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text[:4096]}
        if not 200 <= response.status_code < 300:
            raise LlmProviderError(response.status_code, data)
        return data

    async def _complete_openai(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[CanonicalMessage],
        tools: list[CanonicalTool],
        max_tokens: int,
        temperature: float | None,
    ) -> CanonicalResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [self._openai_message(message) for message in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in tools
            ]
        if temperature is not None:
            payload["temperature"] = temperature
        data = await self._post(
            f"{base_url.rstrip('/')}/chat/completions",
            {"Authorization": f"Bearer {api_key}"},
            payload,
        )
        choice = data["choices"][0]
        message = choice["message"]
        calls = [
            CanonicalToolCall(
                id=item["id"],
                name=item["function"]["name"],
                arguments=json.loads(item["function"].get("arguments") or "{}"),
            )
            for item in message.get("tool_calls", [])
        ]
        usage = data.get("usage", {})
        return CanonicalResponse(
            content=message.get("content") or "",
            tool_calls=calls,
            stop_reason=choice.get("finish_reason"),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    @staticmethod
    def _openai_message(message: CanonicalMessage) -> dict[str, Any]:
        result = {"role": message.role, "content": message.content}
        if message.tool_call_id:
            result["tool_call_id"] = message.tool_call_id
        if message.name:
            result["name"] = message.name
        return result

    async def _complete_anthropic(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[CanonicalMessage],
        tools: list[CanonicalTool],
        max_tokens: int,
        temperature: float | None,
    ) -> CanonicalResponse:
        system = "\n\n".join(
            str(message.content) for message in messages if message.role == "system"
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role != "system"
            ],
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ]
        if temperature is not None:
            payload["temperature"] = temperature
        data = await self._post(
            f"{base_url.rstrip('/')}/messages",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            payload,
        )
        blocks = data.get("content", [])
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        calls = [
            CanonicalToolCall(
                id=block["id"], name=block["name"], arguments=block.get("input", {})
            )
            for block in blocks
            if block.get("type") == "tool_use"
        ]
        usage = data.get("usage", {})
        return CanonicalResponse(
            content=text,
            tool_calls=calls,
            stop_reason=data.get("stop_reason"),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
