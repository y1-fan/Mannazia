from __future__ import annotations

import asyncio
import functools
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.config import Settings


class URLGuardError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_url") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class ResolvedTarget:
    original_url: str
    connect_url: str
    host: str
    port: int
    ip: str
    host_header: str
    allowed_private: bool = False


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.run_in_executor(
            None,
            functools.partial(
                socket.getaddrinfo,
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            ),
        )
    except socket.gaierror as exc:
        raise URLGuardError(
            f"Could not resolve host '{_safe_host(host)}'.", code="resolution_failed"
        ) from exc
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


def _safe_host(host: str) -> str:
    return host[:200]


def redact_url(url: str) -> str:
    """A URL representation safe for logs and user-facing errors."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[invalid URL]"
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path if len(parts.path) <= 200 else parts.path[:197] + "..."
    return f"{parts.scheme}://{host}{path}"


def is_prohibited_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    ):
        return True
    # Covers shared address space (100.64.0.0/10), documentation ranges and
    # other special-purpose blocks that report is_global == False.
    return not ip.is_global


class URLGuard:
    """Validates URLs and resolves them to a pinned public IP address."""

    def __init__(self, settings: Settings, resolver: Resolver | None = None) -> None:
        self.settings = settings
        self._resolver = resolver or system_resolver
        self._allowed_private_hosts = settings.allowed_private_host_set
        self._allow_private = settings.allow_private_networks

    def _allowed_for_host(self, host: str) -> bool:
        return self._allow_private or host.lower().rstrip(".") in self._allowed_private_hosts

    async def resolve(self, url: str) -> ResolvedTarget:
        if not isinstance(url, str) or not url.strip():
            raise URLGuardError("A URL is required.")
        url = url.strip()
        if len(url) > 4096:
            raise URLGuardError("The URL is too long.", code="url_too_long")
        if any(ord(char) < 32 for char in url):
            raise URLGuardError("The URL contains control characters.")
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise URLGuardError("The URL could not be parsed.") from exc
        if parts.scheme.lower() not in {"http", "https"}:
            raise URLGuardError(
                "Only HTTP and HTTPS URLs are supported.", code="scheme_not_allowed"
            )
        if parts.username is not None or parts.password is not None:
            raise URLGuardError(
                "URLs containing embedded credentials are not allowed.", code="credentials_in_url"
            )
        host = (parts.hostname or "").strip().rstrip(".")
        if not host:
            raise URLGuardError("The URL has no hostname.")
        if len(host) > 253 or any(char.isspace() for char in host):
            raise URLGuardError("The URL hostname is invalid.")
        if host.startswith(".") or ".." in host:
            raise URLGuardError("The URL hostname is invalid.")
        try:
            port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise URLGuardError("The URL has an invalid port.") from exc
        if not 1 <= port <= 65535:
            raise URLGuardError("The URL has an invalid port.")

        allowed_private = self._allowed_for_host(host)
        is_literal = _is_ip_literal(host)
        if is_literal:
            addresses = [host.strip("[]")]
            if not allowed_private and any(is_prohibited_ip(item) for item in addresses):
                raise URLGuardError(
                    "This destination address is not allowed. Mannazia blocks loopback, "
                    "private, link-local and reserved network destinations.",
                    code="blocked_destination",
                )
        else:
            addresses = await self._resolver(host, port)
            if not addresses:
                raise URLGuardError(
                    f"Could not resolve host '{_safe_host(host)}'.", code="resolution_failed"
                )
            if not allowed_private:
                blocked = [item for item in addresses if is_prohibited_ip(item)]
                if blocked:
                    raise URLGuardError(
                        "This hostname resolves to a loopback, private, link-local or reserved "
                        "address. Mannazia blocks it to prevent SSRF. Administrators may allow "
                        "a specific IIIF host explicitly.",
                        code="blocked_destination",
                    )
        ip = addresses[0]
        connect_host = f"[{ip}]" if ":" in ip else ip
        connect_netloc = connect_host
        if parts.port is not None:
            connect_netloc += f":{parts.port}"
        connect_url = urlunsplit(
            (parts.scheme.lower(), connect_netloc, parts.path or "/", parts.query, "")
        )
        host_header = host
        if parts.port is not None and not (
            (parts.scheme.lower() == "http" and parts.port == 80)
            or (parts.scheme.lower() == "https" and parts.port == 443)
        ):
            host_header = f"{host}:{parts.port}"
        return ResolvedTarget(
            original_url=url,
            connect_url=connect_url,
            host=host,
            port=port,
            ip=ip,
            host_header=host_header,
            allowed_private=allowed_private,
        )


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False
