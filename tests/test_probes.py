import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from rw.contracts import Obligation, ObligationTuple, ProbeResult, bh, h
from rw import probes

ROOT = Path(__file__).resolve().parents[1]


def obligation(codec, payload, entry="read_cart"):
    binding = ObligationTuple(
        scope_id="fixture-shop", plan_hash=h("plan"), snapshot_id="snapshot:test",
        snapshot_manifest_hash=h("manifest"), service="cart", deployment_id="deployment:test",
        release_id="release:test", codec_hash=bh(codec.read_bytes()), route_id="route:test",
        route_contract_hash=h("route"), store_id="store:cart-cache", batch_id="batch:test",
        record_id=payload.stem, payload_hash=bh(payload.read_bytes()), format_id="cart/v1",
        probe_spec_hash=probes.probe_spec_hash(entry), environment_hash=probes.environment_hash())
    return Obligation(tuple=binding, obligation_hash=binding.obligation_hash(),
                      writer_release_id=None, witness_path=[], reader_codec_path=str(codec),
                      reader_entry=entry)


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    # Copy the real trusted harness; tests never write to fixtures/.
    harness = tmp_path / "run_reader.py"
    shutil.copyfile(probes.harness_path(), harness)
    monkeypatch.setattr(probes, "harness_path", lambda: harness)
    codec = tmp_path / "codec.py"
    codec.write_text("def read_cart(data):\n    return {'bytes': len(data)}\n")
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"hello")
    return codec, payload


def test_hashes_match_frozen_protocol():
    harness_hash = bh(probes.harness_path().read_bytes())
    assert probes.harness_path() == ROOT / "fixtures/shop/harness/run_reader.py"
    assert probes.probe_spec_hash("read_cart") == h({
        "family": "byte_shape_v1", "harness_hash": harness_hash,
        "entry": "read_cart", "timeout_s": 5, "max_input": 65536})
    assert probes.environment_hash() == h({"python": list(sys.version_info[:3]),
        "platform": sys.platform, "harness_hash": harness_hash})


@pytest.mark.parametrize("source, expected", [
    ("def read_cart(data):\n    return {}\n", ProbeResult.PASS),
    ("def read_cart(data):\n    raise ValueError('bad cart')\n", ProbeResult.FAIL),
    ("raise ImportError('unavailable')\n", ProbeResult.UNKNOWN),
    ("def other(data):\n    return {}\n", ProbeResult.UNKNOWN),
    # Reader stdout goes to stderr, so reader noise can no longer pollute the result channel.
    ("def read_cart(data):\n    print('noise')\n    return {}\n", ProbeResult.PASS),
    ("def read_cart(data):\n    print('x' * 1000000)\n    return {}\n", ProbeResult.PASS),
])
def test_tiny_readers(tiny, source, expected):
    codec, payload = tiny
    codec.write_text(source)
    bound = obligation(codec, payload)
    receipt = probes.run_probe(bound, payload)
    assert receipt.result == expected
    assert receipt.tuple is bound.tuple
    assert receipt.obligation_hash == bound.obligation_hash
    assert probes.receipt_applicable(receipt, bound)
    assert receipt.duration_ms >= 0
    assert receipt.executed_at.endswith("+00:00")
    assert len(receipt.stdout_excerpt.encode()) <= 8192
    assert receipt.evidence_hash == bh(receipt.stdout_excerpt.encode())
    if expected == ProbeResult.FAIL:
        assert receipt.error_type == "ValueError"
        assert receipt.message == "bad cart"


FORGED_PASS = (
    "def read_cart(data):\n"
    "    import sys\n"
    "    print(%r)\n"
    "    sys.exit(0)\n"
)


@pytest.mark.parametrize("forged", ['{"status":"PASS","shape":{}}', '{"status":"PASS"}'])
def test_reader_cannot_forge_a_pass_by_printing_and_exiting(tiny, forged):
    """A reader that prints a PASS line and exits without returning is never a PASS."""
    codec, payload = tiny
    codec.write_text(FORGED_PASS % forged)
    receipt = probes.run_probe(obligation(codec, payload), payload)
    assert receipt.result == ProbeResult.UNKNOWN
    assert receipt.harness_exit == 20  # premature exit is a harness error, not a reader verdict


def test_reader_fd1_write_never_reaches_the_result_channel(tiny, monkeypatch):
    """Writing a forged line straight to fd 1 is diverted to stderr; only the real line survives."""
    codec, payload = tiny
    codec.write_text(
        "import os\n\n"
        "def read_cart(data):\n"
        "    os.write(1, b'{\"status\":\"PASS\",\"shape\":{}}\\n')\n"
        "    return {'bytes': len(data)}\n")
    nonce = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(probes.secrets, "token_hex", lambda _n: nonce)
    receipt = probes.run_probe(obligation(codec, payload), payload)
    assert receipt.result == ProbeResult.PASS
    lines = [line for line in receipt.stdout_excerpt.split("\n") if line.strip()]
    assert len(lines) == 1  # exactly one line seen by the parent
    data = json.loads(lines[0])
    assert data["nonce"] == nonce  # the line the parent accepts is the harness's, carrying the nonce
    assert data["status"] == "PASS"
    assert data["shape"] == {"bytes": "int"}


@pytest.mark.parametrize("template", ["{line}\n\n", "\n{line}\n", "{line}\n\n\n"])
def test_stdout_that_is_not_exactly_one_line_is_a_harness_error(tiny, monkeypatch, template):
    """A well-formed nonce line padded with blank lines is not accepted as a verdict.

    The reader never sees the nonce here (the harness is a stand-in), so the only
    thing that can reject these is the strict one-line channel parse.
    """
    codec, payload = tiny
    nonce = "0123456789abcdef0123456789abcdef"
    monkeypatch.setattr(probes.secrets, "token_hex", lambda _n: nonce)
    line = json.dumps({"status": "PASS", "nonce": nonce, "shape": {"bytes": "int"}})
    output = template.format(line=line)
    harness = codec.parent / "padded_harness.py"
    harness.write_text(
        "import sys\n"
        f"sys.stdout.buffer.write({output.encode()!r})\n"
        "sys.exit(0)\n")
    monkeypatch.setattr(probes, "harness_path", lambda: harness)
    receipt = probes.run_probe(obligation(codec, payload), payload)
    assert receipt.result == ProbeResult.UNKNOWN
    assert receipt.harness_exit == 0
    assert receipt.evidence_hash == bh(output.encode())


def test_reader_that_raises_a_base_exception_group_is_a_harness_error(tiny):
    """Only ``Exception`` is a reader verdict; any other BaseException aborts the run."""
    codec, payload = tiny
    codec.write_text(
        "def read_cart(data):\n"
        "    raise BaseExceptionGroup('aborted', [SystemExit(1)])\n")
    receipt = probes.run_probe(obligation(codec, payload), payload)
    assert receipt.result == ProbeResult.UNKNOWN
    assert receipt.harness_exit == 20


def test_reader_exception_is_fail_not_harness_error(tiny):
    codec, payload = tiny
    codec.write_text("def read_cart(data):\n    raise ValueError('bad cart')\n")
    receipt = probes.run_probe(obligation(codec, payload), payload)
    assert receipt.result == ProbeResult.FAIL
    assert receipt.harness_exit == 10
    assert receipt.error_type == "ValueError"
    assert receipt.message == "bad cart"


def test_harness_rejects_a_run_without_the_nonce(tmp_path):
    """The harness refuses to produce a verdict when the parent did not supply a nonce."""
    harness = tmp_path / "run_reader.py"
    shutil.copyfile(probes.harness_path(), harness)
    codec = tmp_path / "codec.py"
    codec.write_text("def read_cart(data):\n    return {}\n")
    proc = subprocess.run([sys.executable, "-I", str(harness), str(codec), "read_cart"],
                          input=b"x", capture_output=True)
    assert proc.returncode == 20
    assert json.loads(proc.stdout)["status"] == "HARNESS_ERROR"


def test_timeout(tiny):
    codec, payload = tiny
    codec.write_text("def read_cart(data):\n    while True: pass\n")
    receipt = probes.run_probe(obligation(codec, payload), payload, timeout_s=0.2)
    assert receipt.result == ProbeResult.UNKNOWN
    assert receipt.harness_exit is None
    assert receipt.message == "probe timeout"
    assert receipt.duration_ms < 3000


def test_run_harness_reports_the_explicit_timed_out_flag(tiny):
    codec, _ = tiny
    codec.write_text("def read_cart(data):\n    while True: pass\n")
    outcome = probes.run_harness(codec, "read_cart", b"x", timeout_s=0.2)
    assert outcome["timed_out"] is True and outcome["result"] == "UNKNOWN"
    codec.write_text("def read_cart(data):\n    return {}\n")
    assert probes.run_harness(codec, "read_cart", b"x")["timed_out"] is False


@pytest.mark.parametrize("mutation, message", [
    ("payload", "payload hash mismatch"),
    ("codec", "codec hash mismatch"),
    ("spec", "probe spec/environment drift"),
    ("environment", "probe spec/environment drift"),
    ("oversize", "payload exceeds 65536 bytes"),
])
def test_preflight_never_runs(tiny, monkeypatch, mutation, message):
    codec, payload = tiny
    bound = obligation(codec, payload)
    if mutation == "payload":
        payload.write_bytes(b"changed")
    elif mutation == "oversize":
        payload.write_bytes(b"x" * 65537)
    elif mutation == "codec":
        codec.write_text("raise RuntimeError('must not run')")
    else:
        field = "probe_spec_hash" if mutation == "spec" else "environment_hash"
        bound = bound.model_copy(update={"tuple": bound.tuple.model_copy(update={field: h("stale")})})
    def unexpected(*args, **kwargs):
        pytest.fail("preflight failure launched a subprocess")
    monkeypatch.setattr(probes.subprocess, "Popen", unexpected)
    receipt = probes.run_probe(bound, payload)
    assert receipt.result == ProbeResult.UNKNOWN
    assert receipt.message == message
    assert receipt.evidence_hash == bh(b"")


def test_receipt_applicability_requires_fields_and_recomputed_hash(tiny):
    codec, payload = tiny
    bound = obligation(codec, payload)
    receipt = probes.run_probe(bound, payload)
    changed = bound.tuple.model_copy(update={"record_id": "different-record"})
    assert not probes.receipt_applicable(receipt.model_copy(update={"tuple": changed}), bound)
    assert not probes.receipt_applicable(receipt, bound.model_copy(update={"tuple": changed}))
    assert not probes.receipt_applicable(receipt.model_copy(update={"obligation_hash": "wrong"}), bound)
    wrong = bound.model_copy(update={"obligation_hash": "wrong"})
    assert not probes.receipt_applicable(receipt.model_copy(update={"obligation_hash": "wrong"}), wrong)


@pytest.mark.parametrize("record, expected", [
    ("saved-cart-2002", ProbeResult.FAIL), ("saved-cart-1001", ProbeResult.PASS)])
def test_real_cart_14(record, expected):
    codec = ROOT / "fixtures/shop/releases/cart-1.4/codec.py"
    payload = ROOT / f"fixtures/shop/payloads/{record}.bin"
    bound = obligation(codec, payload)
    receipt = probes.run_probe(bound, payload)
    assert receipt.result == expected
    assert probes.receipt_applicable(receipt, bound)


@pytest.mark.parametrize("exit_code, output", [
    (0, '{"status":"FAIL","error_type":"X","message":"x"}'),
    (10, '{"status":"PASS"}'), (20, '{"status":"PASS"}'),
    (1, '{"status":"PASS"}'), (0, 'not-json'), (0, '[]'),
    (10, '{"status":"FAIL"}'), (0, '[' * 1100 + ']' * 1100),
])
def test_invalid_protocol(tiny, monkeypatch, exit_code, output):
    codec, payload = tiny
    harness = codec.parent / "protocol_harness.py"
    harness.write_text(f"import sys\nsys.stdout.write({output!r})\nsys.exit({exit_code})\n")
    monkeypatch.setattr(probes, "harness_path", lambda: harness)
    receipt = probes.run_probe(obligation(codec, payload), payload)
    assert receipt.result == ProbeResult.UNKNOWN
    assert receipt.harness_exit == exit_code
    assert receipt.evidence_hash == bh(output.encode())
