from __future__ import annotations

import socket

import app.network as network


def test_network_interfaces_deduplicates_and_filters_addresses(monkeypatch):
    monkeypatch.setattr(
        network,
        "_hostname_ipv4_addresses",
        lambda: iter(["127.0.0.1", "192.168.10.25", "192.168.10.25", "0.0.0.0"]),
    )
    monkeypatch.setattr(
        network,
        "_route_ipv4_addresses",
        lambda: iter(["10.0.0.5", "not-an-ip"]),
    )

    rows = network.network_interfaces(8000)

    assert rows == [
        {
            "name": "Сетевой интерфейс",
            "ip": "192.168.10.25",
            "netmask": "",
            "base_url": "http://192.168.10.25:8000",
        },
        {
            "name": "Сетевой интерфейс 2",
            "ip": "10.0.0.5",
            "netmask": "",
            "base_url": "http://10.0.0.5:8000",
        },
    ]


def test_route_probe_closes_sockets(monkeypatch):
    created = []

    class FakeSocket:
        def __init__(self, *_args, **_kwargs):
            self.closed = False
            self.target = None
            created.append(self)

        def connect(self, target):
            self.target = target

        def getsockname(self):
            if self.target[0] == "192.0.2.1":
                return ("192.168.1.20", 54321)
            return ("10.20.30.40", 54322)

        def close(self):
            self.closed = True

    monkeypatch.setattr(socket, "socket", FakeSocket)

    assert list(network._route_ipv4_addresses()) == ["192.168.1.20", "10.20.30.40"]
    assert created and all(sock.closed for sock in created)
