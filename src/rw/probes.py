"""Bounded, identity-bound execution of the trusted byte/shape harness."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
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
        process = subprocess.Popen(
            [sys.executable, "-I", str(harness_path()), str(codec), obligation.reader_entry],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError) as exc:
        return receipt(message=str(exc), error_type=type(exc).__name__)

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
    try:
        exit_code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    reader.join()
    writer.join()
    if timed_out:
        return receipt(message="probe timeout")
    if overflow:
        return receipt(message="stdout exceeds 8192 bytes")
    try:
        data = json.loads(bytes(stdout))
        if not isinstance(data, dict):
            raise ValueError("stdout must be an object")
        if exit_code == 0 and data.get("status") == "PASS":
            return receipt(ProbeResult.PASS)
        if exit_code == 10 and data.get("status") == "FAIL":
            if not isinstance(data.get("error_type"), str) or not isinstance(data.get("message"), str):
                raise ValueError("FAIL lacks error_type/message")
            return receipt(ProbeResult.FAIL, data["message"], data["error_type"])
    except (ValueError, UnicodeError, RecursionError):
        pass
    return receipt(message="harness error or invalid stdout")
