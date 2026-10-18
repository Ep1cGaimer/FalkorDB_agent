"""SYNTHETIC FIXTURE — quote 3.1.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Placeholder model of upstream src/quote: this service reads no retained state, so only its
startup check is modeled. Not the upstream binary.
"""


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "quote", "version": "3.1.0"}
