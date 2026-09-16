from __future__ import annotations

import socket
from typing import Any, Iterable


def _usable_ipv4(value: str) -> str | None:
    """Normalize a local IPv4 address and reject unusable listener addresses."""
    ip = (value or "").strip()
    if not ip or ip == "0.0.0.0" or ip.startswith("127."):
        return None
    try:
        socket.inet_aton(ip)
    except OSError:
        return None
    return ip


def _hostname_ipv4_addresses() -> Iterable[str]:
    """Return IPv4 addresses known to Winsock/the local resolver for this host."""
    hostname = socket.gethostname()

    try:
        _host, _aliases, addresses = socket.gethostbyname_ex(hostname)
        yield from addresses
    except OSError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)
        for info in infos:
            yield info[4][0]
    except OSError:
        pass


def _route_ipv4_addresses() -> Iterable[str]:
    """Infer addresses selected by the OS routing table without sending packets.

    UDP ``connect()`` only asks the kernel to select a route/local address; no
    datagram is transmitted here.  This is a fallback for systems where the
    hostname is not registered with all local IPv4 addresses.
    """
    for target in (("192.0.2.1", 9), ("198.51.100.1", 9)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(target)
            yield sock.getsockname()[0]
        except OSError:
            pass
        finally:
            sock.close()


def network_interfaces(port: int) -> list[dict[str, Any]]:
    """Return local IPv4 addresses for links shown to LAN clients.

    The implementation intentionally uses only Python's standard ``socket``
    module.  It avoids the psutil native extension and process/system-inspection
    surface that is unnecessary for Turnirium's LAN address discovery.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    candidates = list(_hostname_ipv4_addresses())
    candidates.extend(_route_ipv4_addresses())

    for candidate in candidates:
        ip = _usable_ipv4(candidate)
        if ip is None or ip in seen:
            continue
        seen.add(ip)
        rows.append(
            {
                "name": "Сетевой интерфейс" if len(rows) == 0 else f"Сетевой интерфейс {len(rows) + 1}",
                "ip": ip,
                "netmask": "",
                "base_url": f"http://{ip}:{port}",
            }
        )

    return rows
