"""Observed API representation and strict mismatch/encoding rejection."""
import base64
import hashlib
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def verify(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "evals"))
    return importlib.import_module("confirmatory.file_identity").verify_file_identity


@pytest.mark.parametrize("hex_text", [False, True])
def test_provider_digest_representations_preserve_exact_identity(verify, hex_text):
    data = b"Development file identity check.\n"
    digest = hashlib.sha256(data)
    encoded = base64.b64encode(digest.hexdigest().encode() if hex_text else digest.digest()).decode()
    result = verify({"sha256Hash": encoded, "sizeBytes": str(len(data))},
                    expected_sha256=digest.hexdigest(), expected_bytes=len(data))
    assert result["sha256"] == digest.hexdigest() and result["bytes"] == len(data)
    assert result["provider_digest_representation"] == ("base64-ascii-hex-digest" if hex_text else "base64-digest-bytes")


@pytest.mark.parametrize("encoded", ["not base64!", "", base64.b64encode(b"x" * 64).decode(),
                                     base64.b64encode(b"a" * 31).decode(), "A" * 200])
def test_malformed_digest_cannot_be_used_for_a_corpus_count(verify, encoded):
    with pytest.raises(ValueError):
        verify({"sha256Hash": encoded, "sizeBytes": "10"}, expected_sha256="a" * 64, expected_bytes=10)


@pytest.mark.parametrize("size", [True, "-1", "1.0", "01", None, 9])
def test_size_mismatch_and_noncanonical_sizes_are_rejected(verify, size):
    encoded = base64.b64encode(bytes.fromhex("a" * 64)).decode()
    with pytest.raises(ValueError):
        verify({"sha256Hash": encoded, "sizeBytes": size}, expected_sha256="a" * 64, expected_bytes=10)


def test_well_formed_but_wrong_digest_is_rejected(verify):
    encoded = base64.b64encode(b"f" * 64).decode()
    with pytest.raises(ValueError, match="mismatch"):
        verify({"sha256Hash": encoded, "sizeBytes": "10"}, expected_sha256="a" * 64, expected_bytes=10)
