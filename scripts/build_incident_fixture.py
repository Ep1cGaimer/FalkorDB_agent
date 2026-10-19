#!/usr/bin/env python3
"""SYNTHETIC FIXTURE — deterministic generator for fixtures/astronomy-incident.

A wider Astronomy Shop incident: 12 services and three retained stores. Data flows across two hops:
checkout writes Kafka `orders`; accounting consumes them and writes Postgres `ledger` rows, each one
derived from the order it booked (manifest field `derived_from`). Valkey `cart-cache` is an
unaffected third store.

Hand-written releases (accounting, checkout, fraud-detection, recommendation) live in the fixture.
This script writes the templated releases (cart and the stateless services), every payload from the
real release codecs, and the snapshot manifests whose payload hashes cover those exact bytes. Order
generation reuses scripts/build_astronomy_fixture.py, so the `orders` bytes match that fixture.
Running this twice produces byte-identical output.
"""

import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "astronomy-incident"
RELEASES = FIXTURES / "releases"
PAYLOADS = FIXTURES / "payloads"
SNAPSHOTS = FIXTURES / "snapshots"

CAPTURED_AT = "2026-10-16T21:40:00Z"
ENVIRONMENT = "fixture-local"
USD, LOCAL = "OrderResult/USD", "OrderResult/local-currency"
LEDGER_V1, LEDGER_V2 = "ledger/v1", "ledger/v2"
CART = "Cart/v1"
USD_COUNT, LOCAL_COUNT, CART_COUNT = 24, 16, 20
PARTITIONS = 3
BUILT = {"3.1.0": ("2026-09-18T18:03:28Z", "otel-demo-3.1.0"), "3.2.0": ("2026-10-13T09:00:00Z", "otel-demo-3.2.0")}
HEADER = {
    "3.1.0": "SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); describes upstream 3.1.0 behavior.",
    "3.2.0": ("SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); release 3.2.0 is authored "
              "for this demo, not an upstream release."),
}

# Services that read no retained state: (3.1.0 bullets, 3.2.0 bullets).
STATELESS = {
    "frontend": (["Storefront. Calls backend services over gRPC/HTTP; reads no Kafka, cache or database state directly."],
                 ["No functional change; rebuilt for release train otel-demo-3.2.0. Reads no retained state."]),
    "currency": (["Converts amounts between currencies (including EUR, GBP, CAD and JPY) from a static rate table. Stateless."],
                 ["No functional change; rebuilt for release train otel-demo-3.2.0."]),
    "payment": (["Charges the credit card for an order. Keeps no retained state."],
                ["No functional change; rebuilt for release train otel-demo-3.2.0."]),
    "shipping": (["Quotes and ships orders (calls quote). Keeps no retained state."],
                 ["No functional change; rebuilt for release train otel-demo-3.2.0."]),
    "email": (["Sends order confirmation emails. Keeps no retained state."],
              ["No functional change; rebuilt for release train otel-demo-3.2.0."]),
    "ad": (["Serves contextual ads. Keeps no retained state."],
           ["No functional change; rebuilt for release train otel-demo-3.2.0."]),
    "quote": (["Computes shipping quotes. Keeps no retained state."],
              ["No functional change; rebuilt for release train otel-demo-3.2.0."]),
}
CART_NOTES = {
    "3.1.0": ["Stores each shopper's cart in Valkey (`cart-cache`) as a protobuf `Cart`; reads it back on every request."],
    "3.2.0": ["Saved carts now expire after 60 days instead of 30 (Valkey TTL). The stored `Cart` layout is unchanged.",
              "Shipped in release train otel-demo-3.2.0."],
}
SERVICES = ["accounting", "ad", "cart", "checkout", "currency", "email", "fraud-detection", "frontend",
            "payment", "quote", "recommendation", "shipping"]

STATELESS_CODEC = '''"""SYNTHETIC FIXTURE — {service} {version} (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Placeholder model of upstream src/{service}: this service reads no retained state, so only its
startup check is modeled. Not the upstream binary.
"""


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {{"status": "ok", "service": "{service}", "version": "{version}"}}
'''

CART_CODEC = '''"""SYNTHETIC FIXTURE — cart {version} (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Models upstream src/cart storing demo.proto `Cart` (user_id=1, items=2 of CartItem product_id=1,
quantity=2) in Valkey. Stdlib-only Python model of that step, not the upstream binary.
"""

FORMAT = "Cart/v1"


class InvalidProtocolBufferException(ValueError):
    """Raised for malformed protobuf input."""


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _string(number, text):
    data = text.encode("utf-8")
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def write_cart(cart: dict, flags: dict) -> bytes:
    """Serialize a cart as protobuf `Cart` bytes for Valkey."""
    out = _string(1, cart["user_id"])
    for item in cart["items"]:
        body = _string(1, item["product_id"]) + _varint(2 << 3) + _varint(item["quantity"])
        out += _varint(2 << 3 | 2) + _varint(len(body)) + body
    return out


def _fields(buf):
    pos, fields = 0, []
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 2:
            size, pos = _read_varint(buf, pos)
            if pos + size > len(buf):
                raise InvalidProtocolBufferException("truncated length-delimited field")
            value, pos = buf[pos:pos + size], pos + size
        else:
            raise InvalidProtocolBufferException(f"unsupported wire type {{wire}}")
        fields.append((number, value))
    return fields


def _read_varint(buf, pos):
    result, shift = 0, 0
    while True:
        if pos >= len(buf):
            raise InvalidProtocolBufferException("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def read_cart(data: bytes) -> dict:
    """Load one saved cart from Valkey (GetCart)."""
    fields = _fields(data)
    user = [v for n, v in fields if n == 1]
    if not user:
        raise InvalidProtocolBufferException("Cart has no user_id")
    items = [dict(_fields(v)) for n, v in fields if n == 2]
    for item in items:
        if 1 not in item or not isinstance(item.get(2), int):
            raise InvalidProtocolBufferException("CartItem requires product_id and quantity")
    return {{"format": FORMAT, "user_id": user[0].decode("utf-8"), "item_count": len(items)}}


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {{"status": "ok", "service": "cart", "version": "{version}"}}
'''


def bh(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, obj):
    write_bytes(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def codec(release_dir):
    return load_module(RELEASES / release_dir / "codec.py", "incident_" + release_dir.replace("-", "_").replace(".", "_"))


def release(service, version, routes, writes, notes, codec_text):
    built_at, bundle = BUILT[version]
    folder = RELEASES / f"{service}-{version}"
    write_json(folder / "release.json", {
        "built_at": built_at, "bundle_id": bundle, "flags": [], "no_state_read": not routes,
        "previous_version": "3.1.0" if version == "3.2.0" else None, "routes": routes,
        "service": service, "version": version, "writes": writes})
    write_bytes(folder / "CHANGELOG.md", (f"{HEADER[version]}\n\n## {version}\n\n"
                                          + "".join(f"- {n}\n" for n in notes)).encode("utf-8"))
    write_bytes(folder / "codec.py", codec_text.encode("utf-8"))


def write_templated_releases():
    for service, notes in STATELESS.items():
        for version, bullets in zip(("3.1.0", "3.2.0"), notes):
            release(service, version, [], [], bullets, STATELESS_CODEC.format(service=service, version=version))
    route = {"contract": "valkey/Cart", "entry": "read_cart", "name": "load_cart", "read_domain": "ALL_KEYS",
             "reads_from": "cart-cache"}
    for version in ("3.1.0", "3.2.0"):
        release("cart", version, [route], [{"entry": "write_cart", "store": "cart-cache"}], CART_NOTES[version],
                CART_CODEC.format(version=version))


def record(record_id, writer, fmt, derived_from=None):
    entry = {"record_id": record_id, "payload": f"payloads/{record_id}.bin",
             "payload_hash": bh((PAYLOADS / f"{record_id}.bin").read_bytes()), "writer": writer, "format": fmt}
    if derived_from:
        entry["derived_from"] = derived_from
    return entry


def manifest(name, stores):
    deployments = [{"service": s, "version": "3.2.0",
                    "flags": {"localCurrencyCheckout": True} if s == "checkout" else {}} for s in SERVICES]
    return {"snapshot": name, "captured_at": CAPTURED_AT, "environment": ENVIRONMENT,
            "deployments": deployments, "stores": stores}


def main():
    write_templated_releases()
    shop = load_module(ROOT / "scripts" / "build_astronomy_fixture.py", "astronomy_generator")
    checkout = {v: codec(f"checkout-{v}") for v in ("3.1.0", "3.2.0")}
    accounting = {v: codec(f"accounting-{v}") for v in ("3.1.0", "3.2.0")}
    cart = {v: codec(f"cart-{v}") for v in ("3.1.0", "3.2.0")}
    rng = random.Random(20261017)  # same seed and sequence as fixtures/astronomy-shop

    for stale in PAYLOADS.glob("*.bin") if PAYLOADS.is_dir() else []:
        stale.unlink()

    # orders: 3.1.0 (USD) traffic first, then 3.2.0 traffic from shoppers abroad.
    next_offset = {p: 1040 + 17 * p for p in range(PARTITIONS)}
    orders = []
    for index in range(USD_COUNT + LOCAL_COUNT):
        partition = index % PARTITIONS
        record_id = f"orders-{partition}@{next_offset[partition]}"
        next_offset[partition] += 1
        if index < USD_COUNT:
            data = checkout["3.1.0"].write_order(shop.make_order(rng, index), {})
            writer, fmt = {"service": "checkout", "version": "3.1.0"}, USD
        else:
            data = checkout["3.2.0"].write_order(shop.make_order(rng, index, abroad=True), {"localCurrencyCheckout": True})
            writer, fmt = {"service": "checkout", "version": "3.2.0"}, LOCAL
        write_bytes(PAYLOADS / f"{record_id}.bin", data)
        orders.append((record_id, writer, fmt, data))

    # ledger: each order as the accounting release running at the time booked it, decoded from the
    # order's actual bytes. accounting 3.1.0 consumed the USD traffic and skipped orders without a
    # shipping address (its known bug); accounting 3.2.0 consumed the local-currency traffic.
    ledger = []
    for order_id, _, fmt, data in orders:
        version = "3.1.0" if fmt == USD else "3.2.0"
        decoded = accounting[version]._Wire.order_result(data)
        try:
            row = accounting[version].write_ledger_row(decoded)
        except (KeyError, TypeError):
            continue  # 3.1.0 dereferences the missing shipping address; the order never reaches the ledger
        row_id = f"ledger-{1001 + len(ledger)}"
        write_bytes(PAYLOADS / f"{row_id}.bin", row)
        ledger.append((row_id, {"service": "accounting", "version": version}, json.loads(row)["fmt"], [order_id]))

    # A ledger row inserted by an operator replay script: no writer release, no declared layout, no source order.
    orphan_row = f"ledger-{1001 + len(ledger)}"
    write_bytes(PAYLOADS / f"{orphan_row}.bin", accounting["3.1.0"].write_ledger_row(
        accounting["3.1.0"]._Wire.order_result(orders[0][3])))

    # cart-cache: saved carts, written by whichever cart release served the shopper.
    carts = []
    for index in range(CART_COUNT):
        version = "3.1.0" if index < 12 else "3.2.0"
        user_id = "%08x-%04x-4%03x-b%03x-%012x" % (rng.getrandbits(32), rng.getrandbits(16), rng.getrandbits(12),
                                                    rng.getrandbits(12), rng.getrandbits(48))
        items = [{"product_id": p[0], "quantity": rng.randint(1, 3)} for p in rng.sample(shop.PRODUCTS, rng.randint(1, 4))]
        record_id = f"cart-{user_id[:8]}"
        write_bytes(PAYLOADS / f"{record_id}.bin", cart[version].write_cart({"user_id": user_id, "items": items}, {}))
        carts.append((record_id, {"service": "cart", "version": version}, CART))

    def stores(ledger_coverage="COMPLETE", orphan=False):
        ledger_records = [record(r, w, f, d) for r, w, f, d in ledger]
        if orphan:
            ledger_records.append(record(orphan_row, None, None))
        return [
            {"name": "cart-cache", "kind": "kv-cache", "coverage": "COMPLETE",
             "records": [record(r, w, f) for r, w, f in carts]},
            {"name": "ledger", "kind": "postgres-table", "coverage": ledger_coverage, "records": ledger_records},
            {"name": "orders", "kind": "kafka-topic", "coverage": "COMPLETE",
             "records": [record(r, w, f) for r, w, f, _ in orders]},
        ]

    write_json(SNAPSHOTS / "snap-001" / "manifest.json", manifest("snap-001", stores()))
    write_json(SNAPSHOTS / "snap-002-partial" / "manifest.json", manifest("snap-002-partial", stores("PARTIAL")))
    write_json(SNAPSHOTS / "snap-003-orphan" / "manifest.json", manifest("snap-003-orphan", stores(orphan=True)))
    v2 = sum(1 for _, _, f, _ in ledger if f == LEDGER_V2)
    print(f"wrote {len(orders)} orders, {len(ledger)} ledger rows ({v2} {LEDGER_V2}) + 1 orphan, "
          f"{len(carts)} carts and 3 manifests under {FIXTURES}")


if __name__ == "__main__":
    main()
