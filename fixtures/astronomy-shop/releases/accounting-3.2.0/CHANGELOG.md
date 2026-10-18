SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); release 3.2.0 is authored for this demo, not an upstream release.

## 3.2.0

- Handles orders in any supported currency (EUR, GBP, CAD, JPY, USD) and books them converted to USD.
- Fix: orders without a shipping address (digital goods) are now recorded in the ledger. 3.1.0 failed on the missing address, logged OrderParsingFailed and skipped the order.
- Shipped in release train otel-demo-3.2.0.
