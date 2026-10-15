#!/usr/bin/env python3
"""SYNTHETIC FIXTURE — trusted probe harness (byte_shape_v1).

usage: python -I run_reader.py <codec_path> <entry>   (payload bytes on stdin)

The parent supplies a per-run secret in RW_PROBE_NONCE. Everything the reader
writes to stdout (prints and raw ``os.write(1, ...)``) is redirected to stderr
before the codec is loaded, so the reader cannot reach the result channel.
Exactly one JSON line carrying the nonce is written to the real stdout fd by
this harness, and only after it observed the reader return.

exit 0  PASS    reader returned a dict
exit 10 FAIL    reader raised, or returned a non-dict
exit 20 HARNESS_ERROR   harness could not load/call the reader, the reader
                        aborted the process before returning, or the parent did
                        not provide the per-run nonce
"""

import importlib.util
import json
import os
import sys

MAX_INPUT = 65536

# Probe codecs are loaded from the fixture tree; never write bytecode there.
sys.dont_write_bytecode = True


def _emit(saved, obj, code):
    line = json.dumps(obj, sort_keys=True)
    os.write(saved, line.encode("utf-8") + b"\n")
    os._exit(code)


def _harness_error(saved, nonce, message):
    _emit(saved, {"status": "HARNESS_ERROR", "nonce": nonce, "message": message[:500]}, 20)


def main(argv):
    nonce = os.environ.pop("RW_PROBE_NONCE", None)
    if nonce is None:
        os.write(1, json.dumps(
            {"status": "HARNESS_ERROR", "message": "missing RW_PROBE_NONCE"},
            sort_keys=True).encode("utf-8") + b"\n")
        os._exit(20)

    # The real stdout fd (saved) is the result channel. Point fd 1 and sys.stdout
    # at stderr so any reader output is discarded with the parent's stderr.
    saved = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    if len(argv) != 3:
        _harness_error(saved, nonce, "usage: run_reader.py <codec_path> <entry>")
    codec_path, entry_name = argv[1], argv[2]

    try:
        spec = importlib.util.spec_from_file_location("rw_probe_codec", codec_path)
        if spec is None or spec.loader is None:
            _harness_error(saved, nonce, f"cannot load codec {codec_path!r}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except BaseException as exc:
        _harness_error(saved, nonce, f"{type(exc).__name__}: {exc}")

    entry = getattr(module, entry_name, None)
    if not callable(entry):
        _harness_error(saved, nonce, f"entry {entry_name!r} is missing or not callable")

    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        _harness_error(saved, nonce, f"payload exceeds {MAX_INPUT} bytes")

    try:
        result = entry(data)
    except (SystemExit, KeyboardInterrupt, GeneratorExit) as exc:
        _harness_error(saved, nonce, f"reader aborted with {type(exc).__name__}")
    except BaseException as exc:
        _emit(saved, {"status": "FAIL", "nonce": nonce, "error_type": type(exc).__name__,
                      "message": str(exc)[:500]}, 10)

    if not isinstance(result, dict):
        _emit(saved, {"status": "FAIL", "nonce": nonce, "error_type": "NonDictResult",
                      "message": f"entry returned {type(result).__name__}"}, 10)

    shape = {key: type(value).__name__ for key, value in result.items()}
    _emit(saved, {"status": "PASS", "nonce": nonce, "shape": shape}, 0)


if __name__ == "__main__":
    main(sys.argv)
