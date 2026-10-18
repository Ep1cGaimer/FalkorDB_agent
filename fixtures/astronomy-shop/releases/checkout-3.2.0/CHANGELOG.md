SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); release 3.2.0 is authored for this demo, not an upstream release.

## 3.2.0

- Local-currency checkout: orders are now charged in the shopper's selected currency (EUR, GBP, CAD, JPY or USD) and written to `orders` with those amounts; behind flag localCurrencyCheckout (default on).
- Turning localCurrencyCheckout off prices new orders in USD again, exactly as 3.1.0 did. Orders already written in other currencies stay in the topic.
- Consumers must be on 3.2.0 or later to handle non-USD orders.
- Shipped in release train otel-demo-3.2.0 together with accounting 3.2.0, fraud-detection 3.2.0 and recommendation 3.2.0.
