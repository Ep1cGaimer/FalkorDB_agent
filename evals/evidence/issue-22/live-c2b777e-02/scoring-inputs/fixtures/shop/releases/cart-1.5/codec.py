"""SYNTHETIC FIXTURE — cart 1.5 saved-cart codec (stdlib only)."""

import json

FMT_V1 = "cart/v1"
FMT_V2 = "cart/v2"


def write_cart(cart: dict, flags: dict) -> bytes:
    """Persist a saved cart; basket_v2 (default on) selects cart/v2."""
    if flags.get("basket_v2", True):
        lines = [
            {"sku": it["sku"], "qty": it["qty"], "basket": it.get("basket")}
            for it in cart.get("items", [])
        ]
        obj = {
            "fmt": FMT_V2,
            "lines": lines,
            "baskets": [dict(b) for b in cart.get("baskets", [])],
        }
    else:
        items = [{"sku": it["sku"], "qty": it["qty"]} for it in cart.get("items", [])]
        obj = {"fmt": FMT_V1, "items": items}
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def read_cart(data: bytes) -> dict:
    """Read cart/v1 or cart/v2 bytes; raise ValueError for anything else."""
    obj = json.loads(data)
    fmt = obj.get("fmt")
    if fmt == FMT_V1:
        items = obj.get("items")
        if not isinstance(items, list):
            raise ValueError("cart/v1 requires an items list")
        for it in items:
            if not isinstance(it, dict):
                raise ValueError("cart/v1 items must be objects")
            if not isinstance(it.get("sku"), str) or not isinstance(it.get("qty"), int):
                raise ValueError("cart/v1 items must be {sku: str, qty: int}")
        return {"format": FMT_V1, "item_count": len(items)}
    if fmt == FMT_V2:
        lines = obj.get("lines")
        baskets = obj.get("baskets")
        if not isinstance(lines, list) or not isinstance(baskets, list):
            raise ValueError("cart/v2 requires lines and baskets lists")
        for ln in lines:
            if not isinstance(ln, dict):
                raise ValueError("cart/v2 lines must be objects")
            if not isinstance(ln.get("sku"), str) or not isinstance(ln.get("qty"), int):
                raise ValueError("cart/v2 lines must be {sku: str, qty: int}")
        return {"format": FMT_V2, "item_count": len(lines), "basket_count": len(baskets)}
    raise ValueError(f"unsupported saved-cart format {fmt!r}")


def health(data: bytes = b"") -> dict:
    """Startup/readiness check: the build loads and answers. Reads no retained state."""
    return {"status": "ok", "service": "cart", "version": "1.5"}
