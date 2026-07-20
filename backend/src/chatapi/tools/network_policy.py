import asyncio
import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Any

import httpx

Resolver = Callable[..., Sequence[tuple[Any, ...]]]


class UnsafeNetworkTarget(ValueError):
    pass


def _is_safe_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global


async def validate_network_target(
    url: httpx.URL,
    allow_private_networks: bool,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> None:
    if url.scheme not in {"http", "https"}:
        raise UnsafeNetworkTarget("Only HTTP and HTTPS targets are allowed")
    if url.userinfo:
        raise UnsafeNetworkTarget("Credentials in target URLs are not allowed")
    host = url.host
    if not host:
        raise UnsafeNetworkTarget("Target URL must include a host")
    if allow_private_networks:
        return
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        port = url.port or (443 if url.scheme == "https" else 80)
        try:
            records = await asyncio.to_thread(resolver, host, port, 0, socket.SOCK_STREAM)
        except OSError as exc:
            raise UnsafeNetworkTarget("Target host could not be resolved") from exc
        addresses = list({record[4][0] for record in records})
    if not addresses or any(not _is_safe_address(address) for address in addresses):
        raise UnsafeNetworkTarget("Private or non-routable target addresses are not allowed")
