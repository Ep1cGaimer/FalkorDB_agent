#!/usr/bin/env python3
"""SYNTHETIC FIXTURE — deterministic generator for the shop fixture.

Writes payloads/<record_id>.bin from the real writer codecs, then writes the
snapshot manifests whose payload_hash values cover those exact bytes.
Running this twice produces byte-identical output.

    python scripts/build_fixture.py                 # regenerate fixtures/shop in the repo
    python scripts/build_fixture.py --out SOME_DIR  # generate payloads/ + snapshots/ under SOME_DIR

Output is always relative to the chosen root; the one thing it *reads* as input — the release
``codec.py`` files whose writer functions generate the payloads — always comes from the repo's
fixtures/shop/releases directory, never from --out.
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

# Loading codecs from the fixture tree must not leave __pycache__ directories behind.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
REPO_FIXTURES = ROOT / "fixtures" / "shop"
RELEASES = REPO_FIXTURES / "releases"   # input: release codecs are always read from the repo

CAPTURED_AT = "2026-10-15T08:00:00Z"
ENVIRONMENT = "fixture-local"
STORE = {"name": "cart-cache", "kind": "kv-cache"}


def load_codec(release_dir):
    """Load a release codec.py by path."""
    path = RELEASES / release_dir / "codec.py"
    name = "fixture_codec_" + release_dir.replace("-", "_").replace(".", "_")
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


def record(payloads_dir, record_id, writer, fmt):
    return {
        "record_id": record_id,
        "payload": f"payloads/{record_id}.bin",
        "payload_hash": bh((payloads_dir / f"{record_id}.bin").read_bytes()),
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
            {"service": "cart", "version": "1.5", "flags": {"basket_v2": True}},
            {"service": "checkout", "version": "2.1", "flags": {}},
        ],
        "stores": [store],
    }


def build(out_root):
    """Generate payloads/ and snapshots/ under out_root from the repo release codecs."""
    fixtures = Path(out_root)
    payloads_dir = fixtures / "payloads"
    snapshots_dir = fixtures / "snapshots"

    cart_14 = load_codec("cart-1.4")
    cart_15 = load_codec("cart-1.5")

    payloads = {
        "saved-cart-1001": cart_14.write_cart(
            {"items": [{"sku": "MUG-01", "qty": 2}, {"sku": "TEA-07", "qty": 1}]}, {}
        ),
        "saved-cart-2002": cart_15.write_cart(
            {
                "items": [
                    {"sku": "MUG-01", "qty": 1, "basket": "gift"},
                    {"sku": "CARD-3", "qty": 1, "basket": "gift"},
                ],
                "baskets": [{"id": "gift", "label": "Gift for Sam"}],
            },
            {"basket_v2": True},
        ),
        "saved-cart-3003": cart_14.write_cart({"items": [{"sku": "PEN-9", "qty": 3}]}, {}),
    }
    for record_id, data in payloads.items():
        write_bytes(payloads_dir / f"{record_id}.bin", data)

    base_records = [
        record(payloads_dir, "saved-cart-1001", {"service": "cart", "version": "1.4"}, "cart/v1"),
        record(payloads_dir, "saved-cart-2002", {"service": "cart", "version": "1.5"}, "cart/v2"),
    ]
    orphan_records = base_records + [record(payloads_dir, "saved-cart-3003", None, None)]

    write_json(snapshots_dir / "snap-001" / "manifest.json", manifest("snap-001", "COMPLETE", base_records))
    write_json(
        snapshots_dir / "snap-002-partial" / "manifest.json",
        manifest("snap-002-partial", "PARTIAL", base_records),
    )
    write_json(
        snapshots_dir / "snap-003-orphan" / "manifest.json",
        manifest("snap-003-orphan", "COMPLETE", orphan_records),
    )

    print(f"wrote {len(payloads)} payloads and 3 manifests under {fixtures}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Regenerate the deterministic shop fixture.")
    ap.add_argument("--out", default=None,
                    help="directory to generate payloads/ and snapshots/ under "
                         f"(default: the repo's {REPO_FIXTURES}); release codecs are always read from the repo")
    args = ap.parse_args(argv)
    build(args.out if args.out is not None else REPO_FIXTURES)


if __name__ == "__main__":
    main()
