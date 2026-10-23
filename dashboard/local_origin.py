"""Same-origin checks for servers that only serve their own UI.

Kept identical in dashboard/ and speech_web_ui/ (tests/test_local_origin.py
checks this). Other websites open in the operator's browser can send requests
to these servers. A page can't forge the Origin header, and DNS rebinding
needs a domain name in the Host header, so a request is allowed only when its
Host is localhost or an IP address, and its Origin, when present, is that same
host. Requests without an Origin come from non-browser tools and are allowed.
"""

import ipaddress
from urllib.parse import urlsplit


def _host_is_literal(hostname: str) -> bool:
    if hostname == "localhost":
        return True
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def request_allowed(host_header: str | None, origin_header: str | None) -> bool:
    if not host_header:
        return False
    host = host_header.strip().lower()
    try:
        hostname = urlsplit("//" + host).hostname or ""
    except ValueError:
        return False
    if not _host_is_literal(hostname):
        return False
    if origin_header is None:
        return True
    return origin_header.strip().lower() in (f"http://{host}", f"https://{host}")
