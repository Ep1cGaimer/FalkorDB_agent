"""SYNTHETIC FIXTURE — cart 3.2.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Models upstream src/cart storing demo.proto `Cart` (user_id=1, items=2 of CartItem product_id=1,
quantity=2) in Valkey. Stdlib-only Python model of that step, not the upstream binary.
"""

FORMAT = "Cart/v1"


class InvalidProtocolBufferException(ValueError):
    """Raised for malformed protobuf input."""


def _varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _string(number, text):
    data = text.encode("utf-8")
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def write_cart(cart: dict, flags: dict) -> bytes:
    """Serialize a cart as protobuf `Cart` bytes for Valkey."""
    out = _string(1, cart["user_id"])
    for item in cart["items"]:
        body = _string(1, item["product_id"]) + _varint(2 << 3) + _varint(item["quantity"])
        out += _varint(2 << 3 | 2) + _varint(len(body)) + body
    return out


def _fields(buf):
    pos, fields = 0, []
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(buf, pos)
        elif wire == 2:
            size, pos = _read_varint(buf, pos)
            if pos + size > len(buf):
                raise InvalidProtocolBufferException("truncated length-delimited field")
            value, pos = buf[pos:pos + size], pos + size
        else:
            raise InvalidProtocolBufferException(f"unsupported wire type {wire}")
        fields.append((number, value))
    return fields


def _read_varint(buf, pos):
    result, shift = 0, 0
    while True:
        if pos >= len(buf):
            raise InvalidProtocolBufferException("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def read_cart(data: bytes) -> dict:
    """Load one saved cart from Valkey (GetCart)."""
    fields = _fields(data)
    user = [v for n, v in fields if n == 1]
    if not user:
        raise InvalidProtocolBufferException("Cart has no user_id")
    items = [dict(_fields(v)) for n, v in fields if n == 2]
    for item in items:
        if 1 not in item or not isinstance(item.get(2), int):
            raise InvalidProtocolBufferException("CartItem requires product_id and quantity")
    return {"format": FORMAT, "user_id": user[0].decode("utf-8"), "item_count": len(items)}


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "cart", "version": "3.2.0"}
