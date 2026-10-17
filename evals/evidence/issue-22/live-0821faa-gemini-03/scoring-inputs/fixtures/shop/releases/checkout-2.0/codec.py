"""SYNTHETIC FIXTURE — checkout 2.0 pricing codec (stdlib only)."""

import json

FMT = "cart/v1"


def read_cart_for_pricing(data: bytes) -> dict:
    """Read a saved cart for pricing; cart/v1 only."""
    obj = json.loads(data)
    if obj.get("fmt") != FMT:
        raise ValueError(f"unsupported saved-cart format {obj.get('fmt')!r}")
    items = obj.get("items")
    if not isinstance(items, list):
        raise ValueError("cart/v1 requires an items list")
    return {"format": FMT, "priced_lines": len(items)}


def receipt_total(lines: list) -> int:
    """Cents; rounds each line then sums (pre-INC-4471 behaviour)."""
    total = 0
    for line in lines:
        total += int(round(line["price_cents"] * line["qty"]))
    return total


def health(data: bytes = b"") -> dict:
    """Startup/readiness check: the build loads and answers. Reads no retained state."""
    return {"status": "ok", "service": "checkout", "version": "2.0"}
