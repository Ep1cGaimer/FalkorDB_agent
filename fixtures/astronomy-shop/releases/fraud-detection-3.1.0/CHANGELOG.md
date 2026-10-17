SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); describes upstream 3.1.0 behavior.

## 3.1.0

- Consumes `orders` with `auto.offset.reset = earliest` and parses each record with `OrderResult.parseFrom(record.value())`.
- Fraud limits are in US dollars; an order in another currency throws and stops the poll loop.
