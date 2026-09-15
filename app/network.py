from __future__ import annotations

import socket
from typing import Any


def network_interfaces(port: int) -> list[dict[str, Any]]:
    """Возвращает активные IPv4-интерфейсы для ссылок в локальной сети."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        import psutil
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if st is not None and not st.isup:
                continue
            for addr in addrs:
                if addr.family != socket.AF_INET:
                    continue
                ip = (addr.address or "").strip()
                if not ip or ip.startswith("127.") or ip == "0.0.0.0" or ip in seen:
                    continue
                seen.add(ip)
                rows.append({
                    "name": name,
                    "ip": ip,
                    "netmask": addr.netmask or "",
                    "base_url": f"http://{ip}:{port}",
                })
    except Exception:
        pass

    if not rows:
        try:
            infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)
            for info in infos:
                ip = info[4][0]
                if not ip.startswith("127.") and ip not in seen:
                    seen.add(ip)
                    rows.append({"name": "Сетевой интерфейс", "ip": ip, "netmask": "", "base_url": f"http://{ip}:{port}"})
        except Exception:
            pass
    return rows
