#!/usr/bin/env python3
"""SYNTHETIC FIXTURE — trusted probe harness (byte_shape_v1).

usage: python -I run_reader.py <codec_path> <entry>   (payload bytes on stdin)
exit 0  PASS    reader returned a dict
exit 10 FAIL    reader raised, or returned a non-dict
exit 20 HARNESS_ERROR   harness could not load/call the reader
"""

import importlib.util
import json
import sys

MAX_INPUT = 65536

# Probe codecs are loaded from the fixture tree; never write bytecode there.
sys.dont_write_bytecode = True


def _emit(obj, code):
    print(json.dumps(obj, sort_keys=True))
    sys.exit(code)


def _harness_error(message):
    _emit({"status": "HARNESS_ERROR", "message": message[:500]}, 20)


def main(argv):
    if len(argv) != 3:
        _harness_error("usage: run_reader.py <codec_path> <entry>")
    codec_path, entry_name = argv[1], argv[2]

    try:
        spec = importlib.util.spec_from_file_location("rw_probe_codec", codec_path)
        if spec is None or spec.loader is None:
            _harness_error(f"cannot load codec {codec_path!r}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        _harness_error(f"{type(exc).__name__}: {exc}")

    entry = getattr(module, entry_name, None)
    if not callable(entry):
        _harness_error(f"entry {entry_name!r} is missing or not callable")

    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        _harness_error(f"payload exceeds {MAX_INPUT} bytes")

    try:
        result = entry(data)
    except Exception as exc:
        _emit(
            {"status": "FAIL", "error_type": type(exc).__name__, "message": str(exc)[:500]},
            10,
        )

    if not isinstance(result, dict):
        _emit(
            {
                "status": "FAIL",
                "error_type": "NonDictResult",
                "message": f"entry returned {type(result).__name__}",
            },
            10,
        )

    shape = {key: type(value).__name__ for key, value in result.items()}
    _emit({"status": "PASS", "shape": shape}, 0)


if __name__ == "__main__":
    main(sys.argv)
