SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); describes upstream 3.1.0 behavior.

## 3.1.0

- Consumes `orders` and parses each value with `OrderResult.Parser.ParseFrom(message.Value)`.
- Books every amount as US dollars; an order in another currency is rejected (logged as OrderParsingFailed) and not recorded in the ledger.
- Writes order, orderitem and shipping rows to Postgres schema `accounting`.
