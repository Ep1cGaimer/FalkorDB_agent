SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); describes upstream 3.1.0 behavior.

## 3.1.0

- Stores each shopper's cart in Valkey (`cart-cache`) as a protobuf `Cart`; reads it back on every request.
