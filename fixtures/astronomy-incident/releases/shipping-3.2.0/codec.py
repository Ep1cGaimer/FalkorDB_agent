"""SYNTHETIC FIXTURE — shipping 3.2.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Placeholder model of upstream src/shipping: this service reads no retained state, so only its
startup check is modeled. Not the upstream binary.
"""


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "shipping", "version": "3.2.0"}
