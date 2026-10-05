"""Integratsiya mijozlari uchun umumiy httpx sozlamasi.

Testlar tashqi xizmatga (HEMIS, turniket) hech qachon murojaat qilmasligi
uchun transport bitta joydan almashtiriladi — set_transport_for_tests.
"""

import httpx

_transport: httpx.AsyncBaseTransport | None = None


def set_transport_for_tests(transport: httpx.AsyncBaseTransport | None) -> None:
    """Faqat testlar uchun: barcha integratsiya so'rovlari shu transport orqali o'tadi."""
    global _transport
    _transport = transport


def make_client(
    *,
    timeout: float,
    auth: httpx.Auth | None = None,
    verify: bool = True,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=_transport,
        timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
        auth=auth,
        verify=verify,
        headers=headers,
        follow_redirects=False,
    )
