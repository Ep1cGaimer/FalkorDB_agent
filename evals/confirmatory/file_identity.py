"""Strict digest/size verification for uploaded development corpus files.

The observed Files API also returns base64 ASCII hexadecimal digests. Normalize
that exact representation explicitly; never accept a digest/size mismatch.
"""
import base64
import binascii
import re


def verify_file_identity(metadata: dict, *, expected_sha256: str, expected_bytes: int) -> dict:
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("canonical expected SHA256 required")
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise ValueError("expected byte count must be nonnegative integer")
    encoded = metadata.get("sha256Hash")
    if not isinstance(encoded, str) or not 1 <= len(encoded) <= 128:
        raise ValueError("missing or oversized provider digest")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("invalid base64 provider digest") from None
    if len(decoded) == 32:
        digest, representation = decoded.hex(), "base64-digest-bytes"
    elif re.fullmatch(rb"[0-9a-fA-F]{64}", decoded):
        digest, representation = decoded.decode("ascii").lower(), "base64-ascii-hex-digest"
    else:
        raise ValueError("unsupported provider digest representation")
    size = metadata.get("sizeBytes")
    if type(size) is int:
        normalized_size = size
    elif isinstance(size, str) and re.fullmatch(r"0|[1-9][0-9]*", size):
        normalized_size = int(size)
    else:
        raise ValueError("invalid provider byte count")
    if digest != expected_sha256 or normalized_size != expected_bytes:
        raise ValueError("uploaded content identity mismatch")
    return {"sha256": digest, "bytes": normalized_size, "provider_digest_representation": representation}
