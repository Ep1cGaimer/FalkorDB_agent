#!/usr/bin/env python3
"""SYNTHETIC FIXTURE — deterministic generator for fixtures/astronomy-shop.

Models retained Kafka `orders` messages of the OpenTelemetry Demo (Astronomy Shop, Apache-2.0).
Writes payloads/<record_id>.bin from the real checkout writer codecs, then writes the snapshot
manifests whose payload_hash values cover those exact bytes. Product ids and prices are taken from
upstream src/postgresql/init.sql at tag 3.1.0. Running this twice produces byte-identical output.
"""

import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

# Loading codecs from the fixture tree must not leave __pycache__ directories behind.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "astronomy-shop"
RELEASES = FIXTURES / "releases"
PAYLOADS = FIXTURES / "payloads"
SNAPSHOTS = FIXTURES / "snapshots"

CAPTURED_AT = "2026-10-16T21:40:00Z"
ENVIRONMENT = "fixture-local"
STORE = {"name": "orders", "kind": "kafka-topic"}
USD, LOCAL = "OrderResult/USD", "OrderResult/local-currency"
USD_COUNT, LOCAL_COUNT = 24, 16
PARTITIONS = 3

# (product id, unit price units, unit price nanos) from upstream catalog.products.
PRODUCTS = [
    ("OLJCESPC7Z", 101, 960000000),  # National Park Foundation Explorascope
    ("66VCHSJNUP", 349, 950000000),  # Starsense Explorer Refractor Telescope
    ("1YMWWN1N4O", 129, 950000000),  # Eclipsmart Travel Refractor Telescope
    ("L9ECAV7KIM", 21, 950000000),   # Lens Cleaning Kit
    ("2ZYFJ3GM2N", 209, 950000000),  # Roof Binoculars
    ("0PUK6V6EV0", 175, 0),          # Solar System Color Imager
    ("LS4PSXUNUM", 57, 80000000),    # Red Flashlight
    ("9SIQT8TOJO", 3599, 0),         # Optical Tube Assembly
    ("6E92ZMYYFZ", 69, 950000000),   # Solar Filter
    ("HQTGWGPNH4", 0, 990000000),    # The Comet Book
]
ADDRESSES = [
    ("1600 Amphitheatre Parkway", "Mountain View", "CA", "United States", "94043"),
    ("1 Hacker Way", "Menlo Park", "CA", "United States", "94025"),
    ("410 Terry Ave N", "Seattle", "WA", "United States", "98109"),
    ("2 Rue du Louvre", "Paris", "IDF", "France", "75001"),
    ("Unter den Linden 77", "Berlin", "BE", "Germany", "10117"),
    ("1-1 Marunouchi", "Tokyo", "13", "Japan", "100-0005"),
    ("10 Downing Street", "London", "LND", "United Kingdom", "SW1A 2AA"),
    ("290 Bremner Blvd", "Toronto", "ON", "Canada", "M5V 3L9"),
]
# The currency a shopper in each country selects in the 3.2.0 storefront.
CURRENCY = {"France": "EUR", "Germany": "EUR", "Japan": "JPY", "United Kingdom": "GBP", "Canada": "CAD"}
US_ADDRESSES, ABROAD_ADDRESSES = ADDRESSES[:3], ADDRESSES[3:]
ADDRESS_KEYS = ("street_address", "city", "state", "country", "zip_code")


def load_codec(release_dir):
    """Load a release codec.py by path."""
    path = RELEASES / release_dir / "codec.py"
    name = "astronomy_codec_" + release_dir.replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load codec at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bh(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path, obj):
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    write_bytes(path, text.encode("utf-8"))


def make_order(rng, index, abroad=False):
    """One OrderResult as checkout builds it, priced in USD; every 7th order is digital (no address).

    An order from abroad carries the shopper's selected currency, which checkout 3.2.0 charges in.
    """
    items = []
    for product_id, units, nanos in rng.sample(PRODUCTS, rng.randint(1, 3)):
        quantity = rng.randint(1, 4)
        items.append({"product_id": product_id, "quantity": quantity,
                      "cost": {"currency_code": "USD", "units": units, "nanos": nanos}})
    digital = index % 7 == 3
    order = {
        "order_id": "%08x-%04x-4%03x-a%03x-%012x" % (rng.getrandbits(32), rng.getrandbits(16),
                                                      rng.getrandbits(12), rng.getrandbits(12),
                                                      rng.getrandbits(48)),
        "shipping_tracking_id": "" if digital else "%08x-%04x-%04x" % (rng.getrandbits(32), rng.getrandbits(16),
                                                                      rng.getrandbits(16)),
        "shipping_cost": {"currency_code": "USD", "units": 0 if digital else rng.randint(5, 40),
                          "nanos": 0 if digital else rng.choice([0, 500000000, 990000000])},
        "shipping_address": None if digital else dict(zip(ADDRESS_KEYS, rng.choice(US_ADDRESSES))),
        "items": items,
    }
    if abroad:
        address = dict(zip(ADDRESS_KEYS, rng.choice(ABROAD_ADDRESSES)))
        order["user_currency"] = CURRENCY[address["country"]]
        if not digital:
            order["shipping_address"] = address
    return order


def record(record_id, writer, fmt):
    return {
        "record_id": record_id,
        "payload": f"payloads/{record_id}.bin",
        "payload_hash": bh((PAYLOADS / f"{record_id}.bin").read_bytes()),
        "writer": writer,
        "format": fmt,
    }


def manifest(name, coverage, records):
    store = dict(STORE, coverage=coverage, records=records)
    return {
        "snapshot": name,
        "captured_at": CAPTURED_AT,
        "environment": ENVIRONMENT,
        "deployments": [
            {"service": "accounting", "version": "3.2.0", "flags": {}},
            {"service": "checkout", "version": "3.2.0", "flags": {"localCurrencyCheckout": True}},
            {"service": "fraud-detection", "version": "3.2.0", "flags": {}},
            {"service": "recommendation", "version": "3.2.0", "flags": {}},
        ],
        "stores": [store],
    }


def main():
    checkout_31 = load_codec("checkout-3.1.0")
    checkout_32 = load_codec("checkout-3.2.0")
    rng = random.Random(20261017)

    for stale in PAYLOADS.glob("*.bin") if PAYLOADS.is_dir() else []:
        stale.unlink()

    # Offsets grow per partition in production order: 3.1.0 (USD) traffic first, then 3.2.0 traffic.
    next_offset = {p: 1040 + 17 * p for p in range(PARTITIONS)}
    records = []
    for index in range(USD_COUNT + LOCAL_COUNT):
        partition = index % PARTITIONS
        record_id = f"orders-{partition}@{next_offset[partition]}"
        next_offset[partition] += 1
        if index < USD_COUNT:
            data = checkout_31.write_order(make_order(rng, index), {})
            writer, fmt = {"service": "checkout", "version": "3.1.0"}, USD
        else:  # 3.2.0 traffic shown here: shoppers abroad, charged in their own currency
            data = checkout_32.write_order(make_order(rng, index, abroad=True), {"localCurrencyCheckout": True})
            writer, fmt = {"service": "checkout", "version": "3.2.0"}, LOCAL
        write_bytes(PAYLOADS / f"{record_id}.bin", data)
        records.append((record_id, writer, fmt))

    # A message re-published by an operator replay tool: no producer release, no declared format.
    orphan_id = f"orders-0@{next_offset[0]}"
    write_bytes(PAYLOADS / f"{orphan_id}.bin", checkout_31.write_order(make_order(rng, 99), {}))

    base = [record(rid, writer, fmt) for rid, writer, fmt in records]
    orphan = base + [record(orphan_id, None, None)]

    write_json(SNAPSHOTS / "snap-001" / "manifest.json", manifest("snap-001", "COMPLETE", base))
    write_json(SNAPSHOTS / "snap-002-partial" / "manifest.json", manifest("snap-002-partial", "PARTIAL", base))
    write_json(SNAPSHOTS / "snap-003-orphan" / "manifest.json", manifest("snap-003-orphan", "COMPLETE", orphan))

    print(f"wrote {len(records) + 1} payloads and 3 manifests under {FIXTURES}")


if __name__ == "__main__":
    main()
