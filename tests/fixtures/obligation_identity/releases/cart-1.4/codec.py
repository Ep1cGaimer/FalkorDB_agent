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


def inspect_cart(data: bytes) -> dict:
    """Read cart/v1 or cart/v2 bytes; raise ValueError for anything else."""
    obj = json.loads(data)
    fmt = obj.get("fmt")
    if fmt == "cart/v1":
        items = obj.get("items")
        if not isinstance(items, list):
            raise ValueError("cart/v1 requires an items list")
        for it in items:
            if not isinstance(it, dict):
                raise ValueError("cart/v1 items must be objects")
            if not isinstance(it.get("sku"), str) or not isinstance(it.get("qty"), int):
                raise ValueError("cart/v1 items must be {sku: str, qty: int}")
        return {"format": "cart/v1", "item_count": len(items)}
    if fmt == "cart/v2":
        lines = obj.get("lines")
        baskets = obj.get("baskets")
        if not isinstance(lines, list) or not isinstance(baskets, list):
            raise ValueError("cart/v2 requires lines and baskets lists")
        for ln in lines:
            if not isinstance(ln, dict):
                raise ValueError("cart/v2 lines must be objects")
            if not isinstance(ln.get("sku"), str) or not isinstance(ln.get("qty"), int):
                raise ValueError("cart/v2 lines must be {sku: str, qty: int}")
        return {"format": "cart/v2", "item_count": len(lines), "basket_count": len(baskets)}
    raise ValueError(f"unsupported saved-cart format {fmt!r}")



def read_archive(data: bytes) -> dict:
    """Read only archived-cart bytes from the independent archive store."""
    obj = json.loads(data)
    if obj.get("fmt") != "cart-archive/v1" or obj.get("archived") is not True:
        raise ValueError("expected an archived cart")
    return {"archived": True}
