"""SYNTHETIC FIXTURE — checkout 3.1.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Models upstream OpenTelemetry Demo 3.1.0 src/checkout/main.go sendToPostProcessor.
Stdlib-only Python model of that step, not the upstream binary.
"""

FORMAT_USD = "OrderResult/USD"


class _Encode:
    """Minimal protobuf wire-format encoder for demo.proto OrderResult (proto3: defaults omitted)."""

    @staticmethod
    def varint(value):
        value &= (1 << 64) - 1
        out = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                out.append(byte | 0x80)
            else:
                out.append(byte)
                return bytes(out)

    @staticmethod
    def string(number, text):
        data = text.encode("utf-8")
        return _Encode.varint(number << 3 | 2) + _Encode.varint(len(data)) + data if data else b""

    @staticmethod
    def integer(number, value):
        return _Encode.varint(number << 3) + _Encode.varint(value) if value else b""

    @staticmethod
    def message(number, body):
        return _Encode.varint(number << 3 | 2) + _Encode.varint(len(body)) + body

    @staticmethod
    def money(money):
        return (_Encode.string(1, money["currency_code"]) + _Encode.integer(2, money["units"])
                + _Encode.integer(3, money["nanos"]))

    @staticmethod
    def order_result(order):
        out = _Encode.string(1, order["order_id"]) + _Encode.string(2, order["shipping_tracking_id"])
        out += _Encode.message(3, _Encode.money(order["shipping_cost"]))
        address = order.get("shipping_address")
        if address:
            body = b"".join(_Encode.string(n, address[k]) for n, k in enumerate(
                ("street_address", "city", "state", "country", "zip_code"), start=1))
            out += _Encode.message(4, body)
        for item in order["items"]:
            cart_item = _Encode.string(1, item["product_id"]) + _Encode.integer(2, item["quantity"])
            out += _Encode.message(5, _Encode.message(1, cart_item) + _Encode.message(2, _Encode.money(item["cost"])))
        return out


def write_order(order: dict, flags: dict) -> bytes:
    """Produce to `orders`: the proto.Marshal(result) bytes, every amount in USD."""
    return _Encode.order_result(order)


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "checkout", "version": "3.1.0"}
