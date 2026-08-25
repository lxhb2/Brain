#!/usr/bin/env python3
"""Publish a stable brain.local alias for the LAN IP."""
from __future__ import annotations

import argparse
import signal
import socket
import sys
import time

from zeroconf import IPVersion, ServiceInfo, Zeroconf


def current_ipv4() -> str | None:
    """Return the address that routes to the LAN, not a VM adapter."""
    for probe in ("223.5.5.5", "119.29.29.29", "8.8.8.8"):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.2)
            sock.connect((probe, 53))
            addr = sock.getsockname()[0]
            sock.close()
            if addr and not addr.startswith("127.") and not addr.startswith("169.254."):
                return addr
        except OSError:
            continue
    return None


def make_info(instance: str, port: int, path: str, addr: str) -> ServiceInfo:
    return ServiceInfo(
        "_http._tcp.local.",
        f"{instance}._http._tcp.local.",
        addresses=[socket.inet_aton(addr)],
        port=port,
        properties={"path": path},
        server="brain.local.",
        host_ttl=120,
        other_ttl=4500,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hostname", default="brain.local")
    args = parser.parse_args()

    hostname = args.hostname.rstrip(".") + "."
    addr = current_ipv4()
    if not addr:
        print("[brain-mdns] No usable LAN IPv4 address yet", flush=True)
        return 2

    zc = Zeroconf(ip_version=IPVersion.V4Only)
    infos = [
        make_info("Brain Web", 8080, "/", addr),
        make_info("Brain Cloud", 8090, "/web/client/", addr),
    ]

    def stop(_signum=None, _frame=None):
        for info in reversed(infos):
            try:
                zc.unregister_service(info)
            except Exception:
                pass
        zc.close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    for info in infos:
        info.server = hostname

    try:
        for info in infos:
            zc.register_service(info)
        print(f"[brain-mdns] Published {hostname[:-1]} -> {addr}", flush=True)

        while True:
            time.sleep(15)
            new_addr = current_ipv4()
            if not new_addr or new_addr == addr:
                continue
            addr = new_addr
            print(f"[brain-mdns] LAN address changed -> {addr}", flush=True)
            for info in infos:
                info.addresses = [socket.inet_aton(addr)]
                zc.update_service(info)
    except SystemExit:
        return 0
    except Exception as exc:
        print(f"[brain-mdns] Failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
