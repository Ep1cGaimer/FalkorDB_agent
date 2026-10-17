"""SYNTHETIC FIXTURE — cart 1.4 saved-cart codec (stdlib only)."""

import json

FMT = "cart/v1"


def write_cart(cart: dict, flags: dict) -> bytes:
    """Persist a saved cart as canonical cart/v1 bytes."""
    items = [{"sku": it["sku"], "qty": it["qty"]} for it in cart.get("items", [])]
    obj = {"fmt": FMT, "items": items}
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def read_cart(data: bytes) -> dict:
    """Read cart/v1 bytes; raise ValueError for anything else."""
    obj = json.loads(data)
    if obj.get("fmt") != FMT:
        raise ValueError(f"unsupported saved-cart format {obj.get('fmt')!r}")
    items = obj.get("items")
    if not isinstance(items, list):
        raise ValueError("cart/v1 requires an items list")
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("cart/v1 items must be objects")
        if not isinstance(it.get("sku"), str) or not isinstance(it.get("qty"), int):
            raise ValueError("cart/v1 items must be {sku: str, qty: int}")
    return {"format": FMT, "item_count": len(items)}


def health(data: bytes = b"") -> dict:
    """Startup/readiness check: the build loads and answers. Reads no retained state."""
    return {"status": "ok", "service": "cart", "version": "1.4"}
