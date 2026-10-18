"""SYNTHETIC FIXTURE — recommendation 3.1.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Models upstream OpenTelemetry Demo 3.1.0 src/recommendation/recommendation_server.py.
Stdlib-only Python model of that step, not the upstream binary.
"""


def rank(product_ids: list, cart_product_ids: list, limit: int = 5) -> list:
    """Recommend a sample of products not already in the cart."""
    candidates = [p for p in product_ids if p not in set(cart_product_ids)]
    return candidates[:limit]


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "recommendation", "version": "3.1.0"}
