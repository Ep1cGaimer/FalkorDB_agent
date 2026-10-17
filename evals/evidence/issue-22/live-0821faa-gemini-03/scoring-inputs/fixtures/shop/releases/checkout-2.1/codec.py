"""SYNTHETIC FIXTURE — checkout 2.1 pricing codec (stdlib only)."""

import json

FMT_V1 = "cart/v1"
FMT_V2 = "cart/v2"


def read_cart_for_pricing(data: bytes) -> dict:
    """Read a saved cart for pricing; accepts cart/v1 and cart/v2."""
    obj = json.loads(data)
    fmt = obj.get("fmt")
    if fmt == FMT_V1:
        lines = obj.get("items")
    elif fmt == FMT_V2:
        lines = obj.get("lines")
    else:
        raise ValueError(f"unsupported saved-cart format {fmt!r}")
    if not isinstance(lines, list):
        raise ValueError(f"{fmt} requires a list of lines")
    return {"format": fmt, "priced_lines": len(lines)}


def receipt_total(lines: list) -> int:
    """Cents; sums unrounded line amounts and rounds once (INC-4471 fix)."""
    return int(round(sum(line["price_cents"] * line["qty"] for line in lines)))


def health(data: bytes = b"") -> dict:
    """Startup/readiness check: the build loads and answers. Reads no retained state."""
    return {"status": "ok", "service": "checkout", "version": "2.1"}
