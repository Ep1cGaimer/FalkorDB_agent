"""SYNTHETIC FIXTURE — accounting 3.2.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Authored 3.2.0 behavior for this demo, built on upstream src/accounting/Consumer.cs ProcessMessage.
Stdlib-only Python model of that step, not the upstream binary.
"""

FORMAT_USD = "OrderResult/USD"
FORMAT_LOCAL = "OrderResult/local-currency"
# Units of each currency per US dollar, as hundredths (same table as checkout 3.2.0).
RATES_PER_USD = {"USD": 100, "EUR": 92, "GBP": 79, "CAD": 137, "JPY": 14950}


class UnsupportedCurrencyError(ValueError):
    """Raised when an order is priced in a currency this build cannot handle."""


class InvalidProtocolBufferException(ValueError):
    """Raised for malformed protobuf input (same name and messages as the protobuf runtimes)."""


class _Wire:
    """Minimal protobuf wire-format decoder for demo.proto OrderResult (proto3, stdlib only)."""

    TRUNCATED = ("While parsing a protocol message, the input ended unexpectedly in the middle "
                 "of a field.")

    @staticmethod
    def varint(buf, pos):
        result, shift = 0, 0
        while True:
            if pos >= len(buf):
                raise InvalidProtocolBufferException(_Wire.TRUNCATED)
            byte = buf[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result, pos
            shift += 7
            if shift >= 70:
                raise InvalidProtocolBufferException("CodedInputStream encountered a malformed varint.")

    @staticmethod
    def fields(buf):
        """Return {field_number: [(wire_type, value), ...]}; unknown fields are kept and ignored later."""
        out, pos = {}, 0
        while pos < len(buf):
            tag, pos = _Wire.varint(buf, pos)
            if tag == 0:
                raise InvalidProtocolBufferException("Protocol message contained an invalid tag (zero).")
            number, wire_type = tag >> 3, tag & 7
            if wire_type == 0:
                value, pos = _Wire.varint(buf, pos)
            elif wire_type == 1:
                if pos + 8 > len(buf):
                    raise InvalidProtocolBufferException(_Wire.TRUNCATED)
                value, pos = buf[pos:pos + 8], pos + 8
            elif wire_type == 2:
                length, pos = _Wire.varint(buf, pos)
                if pos + length > len(buf):
                    raise InvalidProtocolBufferException(_Wire.TRUNCATED)
                value, pos = buf[pos:pos + length], pos + length
            elif wire_type == 5:
                if pos + 4 > len(buf):
                    raise InvalidProtocolBufferException(_Wire.TRUNCATED)
                value, pos = buf[pos:pos + 4], pos + 4
            else:
                raise InvalidProtocolBufferException("Protocol message tag had invalid wire type.")
            out.setdefault(number, []).append((wire_type, value))
        return out

    @staticmethod
    def string(fields, number):
        for wire_type, value in fields.get(number, []):
            if wire_type == 2:
                try:
                    return value.decode("utf-8")
                except UnicodeDecodeError:
                    raise InvalidProtocolBufferException("Protocol message contained an invalid UTF-8 string.")
        return ""

    @staticmethod
    def integer(fields, number):
        for wire_type, value in fields.get(number, []):
            if wire_type == 0:
                return value - (1 << 64) if value >= 1 << 63 else value
        return 0

    @staticmethod
    def messages(fields, number):
        return [_Wire.fields(value) for wire_type, value in fields.get(number, []) if wire_type == 2]

    @staticmethod
    def money(fields):
        return {"currency_code": _Wire.string(fields, 1), "units": _Wire.integer(fields, 2),
                "nanos": _Wire.integer(fields, 3)}

    @staticmethod
    def order_result(buf):
        """Decode OrderResult: order_id=1, shipping_tracking_id=2, shipping_cost=3, shipping_address=4, items=5."""
        f = _Wire.fields(buf)
        cost = _Wire.messages(f, 3)
        address = _Wire.messages(f, 4)
        items = []
        for item in _Wire.messages(f, 5):
            cart_item = (_Wire.messages(item, 1) or [{}])[0]
            item_cost = (_Wire.messages(item, 2) or [{}])[0]
            items.append({"product_id": _Wire.string(cart_item, 1), "quantity": _Wire.integer(cart_item, 2),
                          "cost": _Wire.money(item_cost)})
        return {
            "order_id": _Wire.string(f, 1),
            "shipping_tracking_id": _Wire.string(f, 2),
            "shipping_cost": _Wire.money(cost[0]) if cost else None,
            "shipping_address": ({k: _Wire.string(address[0], n) for n, k in enumerate(
                ("street_address", "city", "state", "country", "zip_code"), start=1)} if address else None),
            "items": items,
        }


def order_currencies(order: dict) -> list[str]:
    """Currency codes used by the order's shipping cost and item prices."""
    costs = [order["shipping_cost"]] + [item["cost"] for item in order["items"]]
    return sorted({cost["currency_code"] for cost in costs if cost and cost["currency_code"]})


def to_usd_nanos(money: dict) -> int:
    """Convert an amount in any supported currency to US dollar nanos."""
    code = money["currency_code"]
    if code not in RATES_PER_USD:
        raise UnsupportedCurrencyError(f"Order is priced in {code}; no exchange rate is known.")
    return (money["units"] * 1_000_000_000 + money["nanos"]) * 100 // RATES_PER_USD[code]


def read_order(data: bytes) -> dict:
    """Consume one `orders` message (var order = OrderResult.Parser.ParseFrom(message.Value);); amounts in any supported currency are converted to USD."""
    order = _Wire.order_result(data)
    codes = order_currencies(order)
    total = sum(to_usd_nanos(item["cost"]) * item["quantity"] for item in order["items"])
    return {"format": FORMAT_USD if codes in ([], ["USD"]) else FORMAT_LOCAL, "order_id": order["order_id"],
            "item_count": len(order["items"]), "total_usd_nanos": total}


def record_order(order: dict) -> dict:
    """Ledger rows for an order; an order without a shipping address gets an empty shipping row."""
    address = order.get("shipping_address") or {}
    return {"order_id": order["order_id"], "items": len(order["items"]),
            "city": address.get("city", ""), "country": address.get("country", "")}


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "accounting", "version": "3.2.0"}
