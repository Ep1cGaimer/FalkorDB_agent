SYNTHETIC FIXTURE — modeled on OpenTelemetry Demo 3.1.0 (Apache-2.0); describes upstream 3.1.0 behavior.

## 3.1.0

- Publishes every placed order to Kafka topic `orders` as protobuf `OrderResult` bytes from `proto.Marshal(result)` (upstream `sendToPostProcessor`).
- Every price and shipping cost in the order is in USD.
- accounting and fraud-detection consume `orders`.
