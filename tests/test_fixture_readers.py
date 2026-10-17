"""SYNTHETIC FIXTURE — tests for the shop fixture payloads, manifests and probe harness."""

import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "shop"
RELEASES = FIXTURES / "releases"
PAYLOADS = FIXTURES / "payloads"
SNAPSHOTS = FIXTURES / "snapshots"
HARNESS = FIXTURES / "harness" / "run_reader.py"
BUILDER = ROOT / "scripts" / "build_fixture.py"

MAX_INPUT = 65536

# Loading codecs from the fixture tree must not leave __pycache__ directories behind.
sys.dont_write_bytecode = True


def codec_path(release_dir):
    return RELEASES / release_dir / "codec.py"


def load_codec(release_dir):
    path = codec_path(release_dir)
    spec = importlib.util.spec_from_file_location(f"test_codec_{release_dir.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_files():
    return sorted(PAYLOADS.glob("*.bin")) + sorted(SNAPSHOTS.glob("*/manifest.json"))


def nonce_env(nonce):
    return {"RW_PROBE_NONCE": nonce,
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PATH": os.environ.get("PATH", "")}


def run_harness(release_dir, entry, payload_bytes, nonce):
    return subprocess.run(
        [sys.executable, "-I", str(HARNESS), str(codec_path(release_dir)), entry],
        input=payload_bytes,
        capture_output=True,
        env=nonce_env(nonce),
    )


def harness_json(proc, nonce):
    text = proc.stdout.decode("utf-8")
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    lines = [line for line in text.split("\n") if line.strip()]
    assert len(lines) == 1, proc.stdout
    data = json.loads(lines[0])
    assert data["nonce"] == nonce
    return data


def test_rebuild_matches_repo_copy_byte_for_byte(tmp_path):
    """``--out`` builds a fresh tree; every generated file is byte-identical to the repo fixture,
    and the repo itself is never touched (git status stays clean)."""
    before = {p.relative_to(FIXTURES).as_posix(): p.read_bytes() for p in fixture_files()}
    assert before, "expected fixture payloads and manifests to exist"

    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--out", str(tmp_path)], cwd=ROOT,
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr

    generated = {p.relative_to(tmp_path).as_posix(): p.read_bytes()
                 for p in tmp_path.rglob("*") if p.is_file()}
    assert generated, "expected payloads and manifests to be generated under --out"
    assert generated.keys() == before.keys(), (sorted(generated), sorted(before))
    for rel, data in before.items():
        assert generated[rel] == data, f"rebuild differs from the repo copy: {rel}"

    repo_after = {p.relative_to(FIXTURES).as_posix(): p.read_bytes() for p in fixture_files()}
    assert repo_after == before, "running the builder with --out changed the repo fixture copy"


def test_manifest_hashes_match_payload_bytes():
    for manifest_path in sorted(SNAPSHOTS.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for store in manifest["stores"]:
            for recording in store["records"]:
                payload = (FIXTURES / recording["payload"]).read_bytes()
                expected = "sha256:" + hashlib.sha256(payload).hexdigest()
                assert recording["payload_hash"] == expected, f"{manifest_path}: {recording['record_id']}"


def test_harness_cart_reads():
    payload_1001 = (PAYLOADS / "saved-cart-1001.bin").read_bytes()
    payload_2002 = (PAYLOADS / "saved-cart-2002.bin").read_bytes()

    nonce = secrets.token_hex(16)
    proc = run_harness("cart-1.4", "read_cart", payload_1001, nonce)
    assert proc.returncode == 0
    data = harness_json(proc, nonce)
    assert data["status"] == "PASS"
    assert data["shape"] == {"format": "str", "item_count": "int"}

    nonce = secrets.token_hex(16)
    proc = run_harness("cart-1.4", "read_cart", payload_2002, nonce)
    assert proc.returncode == 10
    assert harness_json(proc, nonce)["status"] == "FAIL"

    for payload in (payload_1001, payload_2002):
        nonce = secrets.token_hex(16)
        proc = run_harness("cart-1.5", "read_cart", payload, nonce)
        assert proc.returncode == 0, proc.stdout
        assert harness_json(proc, nonce)["status"] == "PASS"


def test_harness_checkout_pricing_reads():
    payload_1001 = (PAYLOADS / "saved-cart-1001.bin").read_bytes()
    payload_2002 = (PAYLOADS / "saved-cart-2002.bin").read_bytes()

    nonce = secrets.token_hex(16)
    proc = run_harness("checkout-2.0", "read_cart_for_pricing", payload_2002, nonce)
    assert proc.returncode == 10
    assert harness_json(proc, nonce)["status"] == "FAIL"

    for payload in (payload_1001, payload_2002):
        nonce = secrets.token_hex(16)
        proc = run_harness("checkout-2.1", "read_cart_for_pricing", payload, nonce)
        assert proc.returncode == 0, proc.stdout
        assert harness_json(proc, nonce)["status"] == "PASS"


def test_harness_errors_are_exit_20():
    payload = (PAYLOADS / "saved-cart-1001.bin").read_bytes()

    nonce = secrets.token_hex(16)
    proc = run_harness("cart-1.4", "no_such_entry", payload, nonce)
    assert proc.returncode == 20
    assert harness_json(proc, nonce)["status"] == "HARNESS_ERROR"

    nonce = secrets.token_hex(16)
    proc = subprocess.run(
        [sys.executable, "-I", str(HARNESS), str(FIXTURES / "nope" / "codec.py"), "read_cart"],
        input=payload,
        capture_output=True,
        env=nonce_env(nonce),
    )
    assert proc.returncode == 20
    assert harness_json(proc, nonce)["status"] == "HARNESS_ERROR"


def test_receipt_total_differs_between_checkout_versions():
    lines = [{"price_cents": 333.335, "qty": 3}, {"price_cents": 0.5, "qty": 1}]
    old = load_codec("checkout-2.0").receipt_total(lines)
    new = load_codec("checkout-2.1").receipt_total(lines)
    assert old != new, "expected the per-line vs once-only rounding to differ"


def test_payload_within_harness_input_cap():
    for path in sorted(PAYLOADS.glob("*.bin")):
        assert path.stat().st_size <= MAX_INPUT
