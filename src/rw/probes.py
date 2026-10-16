"""Bounded, identity-bound execution of the trusted byte/shape harness."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Thread
from time import monotonic

from rw.contracts import Obligation, ProbeReceipt, ProbeResult, bh, h

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_INPUT = 65536
MAX_STDOUT = 8192


def harness_path() -> Path:
    return REPO_ROOT / "fixtures/shop/harness/run_reader.py"


def probe_spec_hash(entry: str) -> str:
    return h({"family": "byte_shape_v1", "harness_hash": bh(harness_path().read_bytes()),
              "entry": entry, "timeout_s": 5, "max_input": MAX_INPUT})


def environment_hash() -> str:
    return h({"python": list(sys.version_info[:3]), "platform": sys.platform,
              "harness_hash": bh(harness_path().read_bytes())})


def receipt_applicable(receipt: ProbeReceipt, obligation: Obligation) -> bool:
    return (receipt.obligation_hash == obligation.obligation_hash
            == obligation.tuple.obligation_hash() and receipt.tuple == obligation.tuple)


def run_harness(codec_path: Path, entry: str, payload: bytes, timeout_s: float = 5) -> dict:
    """Run the trusted harness once on ``payload`` and return its verdict.

    This is the only sanctioned caller of the fixture harness. It owns the
    per-run secret nonce, a minimal child environment, bounded I/O, the
    timeout, and the strict one-line/nonce/schema parsing of the result
    channel. The nonce and the stdout diversion keep ordinary reader output and
    early exits out of the result channel; they are failure containment for
    allowlisted, reviewed fixture readers, not a sandbox against a reader that
    deliberately introspects the live process. Returns::

        {"result": "PASS"|"FAIL"|"UNKNOWN", "exit": int|None, "stdout": bytes,
         "error_type": str|None, "message": str|None, "shape": dict|None}

    ``stdout`` is the raw bytes seen on the result channel (capped at
    ``MAX_STDOUT``). ``stderr`` stays discarded so reader output cannot reach
    the parent as evidence.
    """
    nonce = secrets.token_hex(16)
    outcome = {"result": "UNKNOWN", "exit": None, "stdout": b"",
               "error_type": None, "message": None, "shape": None}

    if timeout_s <= 0:
        outcome["message"] = "invalid timeout"
        return outcome

    codec = Path(codec_path)
    env = {"RW_PROBE_NONCE": nonce,
           "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
           "PATH": os.environ.get("PATH", "")}
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", str(harness_path()), str(codec), entry],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env)
    except (OSError, ValueError) as exc:
        outcome["error_type"] = type(exc).__name__
        outcome["message"] = str(exc)
        return outcome

    stdout = bytearray()
    overflow = []

    def collect():
        with process.stdout as stream:
            while chunk := stream.read1(1024):
                remaining = MAX_STDOUT - len(stdout)
                stdout.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.append(True)
                    process.kill()
                    break

    def feed():
        try:
            with process.stdin as stream:
                stream.write(payload)
        except (BrokenPipeError, OSError):
            pass

    reader = Thread(target=collect, daemon=True)
    writer = Thread(target=feed, daemon=True)
    reader.start()
    writer.start()
    timed_out = False
    exit_code = None
    try:
        exit_code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    reader.join()
    writer.join()

    raw = bytes(stdout)
    outcome["stdout"] = raw
    outcome["exit"] = exit_code
    if timed_out:
        outcome["message"] = "probe timeout"
        return outcome
    if overflow:
        outcome["message"] = "stdout exceeds 8192 bytes"
        return outcome

    try:
        # The harness writes exactly one JSON line. Accept nothing else: the run
        # must end in a single newline and contain no other newline, so padded or
        # blank lines are a harness error rather than a verdict.
        if not (raw.endswith(b"\n") and raw.count(b"\n") == 1):
            raise ValueError("stdout must be exactly one line")
        text = raw[:-1].decode("utf-8")
        if not text.strip():
            raise ValueError("stdout must be exactly one non-empty line")
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("nonce") != nonce:
            raise ValueError("stdout must carry the run nonce")
        if exit_code == 0 and data.get("status") == "PASS" and isinstance(data.get("shape"), dict):
            outcome["result"] = "PASS"
            outcome["shape"] = data["shape"]
            return outcome
        if exit_code == 10 and data.get("status") == "FAIL":
            if not isinstance(data.get("error_type"), str) or not isinstance(data.get("message"), str):
                raise ValueError("FAIL lacks error_type/message")
            outcome["result"] = "FAIL"
            outcome["error_type"] = data["error_type"]
            outcome["message"] = data["message"]
            return outcome
    except (ValueError, UnicodeError, RecursionError):
        pass
    outcome["message"] = "harness error or invalid stdout"
    return outcome


def run_probe(obligation: Obligation, payload_path: Path, timeout_s=5) -> ProbeReceipt:
    started = monotonic()
    executed_at = datetime.now(timezone.utc).isoformat()
    stdout = bytearray()
    exit_code = None

    def receipt(result=ProbeResult.UNKNOWN, message=None, error_type=None):
        raw = bytes(stdout)
        return ProbeReceipt(
            obligation_hash=obligation.obligation_hash, tuple=obligation.tuple,
            result=result, harness_exit=exit_code,
            stdout_excerpt=raw.decode("utf-8", errors="replace"), evidence_hash=bh(raw),
            message=message, error_type=error_type, executed_at=executed_at,
            duration_ms=max(0, int((monotonic() - started) * 1000)))

    try:
        # Read at most one byte past the limit, even for unexpectedly large files.
        with Path(payload_path).open("rb") as stream:
            payload = stream.read(MAX_INPUT + 1)
        if len(payload) > MAX_INPUT:
            return receipt(message="payload exceeds 65536 bytes")
        if bh(payload) != obligation.tuple.payload_hash:
            return receipt(message="payload hash mismatch")
        if (obligation.tuple.probe_spec_hash != probe_spec_hash(obligation.reader_entry)
                or obligation.tuple.environment_hash != environment_hash()):
            return receipt(message="probe spec/environment drift")
        codec = Path(obligation.reader_codec_path)
        if not codec.is_absolute():
            codec = REPO_ROOT / codec
        if bh(codec.read_bytes()) != obligation.tuple.codec_hash:
            return receipt(message="codec hash mismatch")
        if timeout_s <= 0:
            return receipt(message="invalid timeout")
    except (OSError, ValueError) as exc:
        return receipt(message=str(exc), error_type=type(exc).__name__)

    outcome = run_harness(codec, obligation.reader_entry, payload, timeout_s)
    stdout.extend(outcome["stdout"])
    exit_code = outcome["exit"]
    if outcome["result"] == ProbeResult.PASS:
        return receipt(ProbeResult.PASS)
    if outcome["result"] == ProbeResult.FAIL:
        return receipt(ProbeResult.FAIL, outcome["message"], outcome["error_type"])
    return receipt(message=outcome["message"], error_type=outcome["error_type"])
