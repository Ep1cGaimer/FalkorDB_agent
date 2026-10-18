"""SYNTHETIC FIXTURE — accounting 3.1.0 (OpenTelemetry Demo Astronomy Shop, Apache-2.0).

Models upstream OpenTelemetry Demo 3.1.0 src/accounting/Consumer.cs ProcessMessage.
Stdlib-only Python model of that step, not the upstream binary.
"""

import json

FORMAT_USD = "OrderResult/USD"
SUPPORTED_CURRENCIES = ("USD",)  # every amount is handled as US dollars


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


def read_order(data: bytes) -> dict:
    """Consume one `orders` message (var order = OrderResult.Parser.ParseFrom(message.Value);) and handle its amounts as US dollars."""
    order = _Wire.order_result(data)
    for code in order_currencies(order):
        if code not in SUPPORTED_CURRENCIES:
            raise UnsupportedCurrencyError(f"Order is priced in {code}; this build only handles USD.")
    return {"format": FORMAT_USD, "order_id": order["order_id"], "item_count": len(order["items"])}


def record_order(order: dict) -> dict:
    """Ledger rows for an order; reads order.ShippingAddress directly, so a missing address raises."""
    address = order["shipping_address"]
    return {"order_id": order["order_id"], "items": len(order["items"]),
            "city": address["city"], "country": address["country"]}


LEDGER_V1 = "ledger/v1"
LEDGER_V1_COLUMNS = frozenset({"fmt", "order_id", "items", "city", "country", "amount_usd_nanos"})


class UnsupportedLedgerRowError(ValueError):
    """Raised when an `accounting.ledger` row has a layout this build does not map."""


def write_ledger_row(order: dict) -> bytes:
    """Book one consumed (USD) order as an `accounting.ledger` row; a missing address raises (order skipped)."""
    row = record_order(order)
    row["fmt"] = LEDGER_V1
    row["amount_usd_nanos"] = sum((item["cost"]["units"] * 1_000_000_000 + item["cost"]["nanos"]) * item["quantity"]
                                  for item in order["items"])
    return json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_ledger_row(data: bytes) -> dict:
    """Reconcile before booking: load one existing `accounting.ledger` row so a re-delivered order is not booked twice."""
    row = json.loads(data)
    if row.get("fmt") != LEDGER_V1 or set(row) != LEDGER_V1_COLUMNS:
        extra = sorted(set(row) - LEDGER_V1_COLUMNS)
        raise UnsupportedLedgerRowError(
            f"Ledger row layout {row.get('fmt')!r} has columns {extra} this build does not map; cannot reconcile.")
    return {"format": LEDGER_V1, "order_id": row["order_id"], "amount_usd_nanos": row["amount_usd_nanos"]}


def health(data: bytes = b"") -> dict:  # startup check; reads no retained state
    return {"status": "ok", "service": "accounting", "version": "3.1.0"}
