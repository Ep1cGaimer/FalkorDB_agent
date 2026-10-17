# Astronomy Shop fixture plan (OpenTelemetry Demo, Kafka `orders`)

Status: agreed with the owner on 2026-10-17; quick-scope version (about two hours). Replaces the
toy `fixtures/shop` content **for the demo only**; `fixtures/shop` stays the default for tests, the
independent oracle and the SQL control, so nothing already verified changes.

## Why

The `shop` fixture (two services, one cache, two saved carts) reads as a toy. The new fixture models
a real, well-known open-source system, the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo)
("Astronomy Shop", Apache-2.0, ~3.4k stars), at tag **3.1.0**, and adds one authored release train
(**3.2.0**) that introduces a real class of rollback hazard: a Kafka producer starts writing values (prices in
non-USD currencies) that older consumers reject, and those messages stay retained in the topic.

**Update 2026-10-18:** the first version used Confluent Schema Registry framing (a leading `0x00`
byte) as the hazard. It was replaced with local-currency pricing because it is easier to explain on a
whiteboard: *old services only understand dollars; the new checkout writes euros and yen.*

Honest label everywhere it is shown: *"Synthetic data modeled on OpenTelemetry Demo 3.1.0
(Apache-2.0). Release 3.2.0 is authored for this demo."*

## Upstream facts the fixture relies on (verified at tag 3.1.0)

| Fact | Upstream source |
|---|---|
| checkout (Go) marshals `OrderResult` with `proto.Marshal(result)` and produces it to topic `orders` | `src/checkout/main.go` `sendToPostProcessor`, `src/checkout/kafka/producer.go` |
| accounting (.NET) reads with `OrderResult.Parser.ParseFrom(message.Value)`; any exception is caught and logged as `OrderParsingFailed`, so the order is **silently missing from the ledger** | `src/accounting/Consumer.cs` `ProcessMessage` |
| fraud-detection (Kotlin) reads with `OrderResult.parseFrom(record.value())` inside the poll loop with no catch, and uses `auto.offset.reset = earliest` ("Read from the start of the topic") | `src/fraud-detection/src/main/kotlin/frauddetection/main.kt` |
| Every price is a `Money` (currency_code, units, nanos); the frontend lets shoppers pick a currency and the currency service converts | `pb/demo.proto`, `src/currency` |
| `OrderResult` = order_id(1), shipping_tracking_id(2), shipping_cost Money(3), shipping_address Address(4), repeated OrderItem items(5) | `pb/demo.proto` |
| Product ids, names and prices | `src/postgresql/init.sql` (`catalog.products`) |
| All services ship under one demo version (3.1.0) | upstream release tags |

`earliest` offset reset is why the reader route's read domain is *all retained messages*: a consumer
group that is reset, re-created or rebalanced after a rollback can be handed every retained message.

## Authored release train 3.2.0 (bundle `otel-demo-3.2.0`)

| Service | 3.1.0 (upstream behavior) | 3.2.0 (authored) |
|---|---|---|
| checkout | writes `OrderResult` priced in USD | charges shoppers in their selected currency (EUR, GBP, CAD, JPY) and writes those amounts, behind declared flag `localCurrencyCheckout` (default on); flag off writes USD again |
| accounting | books every amount as USD; rejects any other currency | converts any supported currency to USD; also fixes orders without a shipping address (digital goods) being dropped with a `NullReferenceException` |
| fraud-detection | fraud limits in USD; throws on any other currency | converts to USD before applying limits |
| recommendation | upstream ranking | ranking tweak; reads no retained state (the clean rollback) |

checkout and recommendation declare `no_state_read`; accounting and fraud-detection each declare one
reader route `consume_orders` → store `orders` (kind `kafka-topic`, read domain `ALL_KEYS`).

## Retained data

Store `orders`, record ids `orders-<partition>@<offset>`. 40 messages in `snap-001`: 24 in USD
(writer checkout 3.1.0, format `OrderResult/USD`) and 16 from shoppers in France, Germany, the UK,
Japan and Canada priced in their own currency (writer checkout 3.2.0, format
`OrderResult/local-currency`), generated deterministically from real product ids and prices, a few
with no shipping address. Snapshot names match `shop` so the API, UI and scripts need no snapshot changes:

| Snapshot | Content | Purpose |
|---|---|---|
| `snap-001` | 40 messages, coverage COMPLETE | main demo |
| `snap-002-partial` | same messages, coverage PARTIAL | NEEDS_EVIDENCE (`COVERAGE_INCOMPLETE`) |
| `snap-003-orphan` | plus one message with unknown writer/format (an ops replay tool) | NEEDS_EVIDENCE (`WRITER_UNKNOWN`, `FORMAT_UNKNOWN`) |

## Readers and probes

Each release's `codec.py` is a stdlib-only Python model of that release's decode step, with a small
protobuf wire decoder. The 3.1.0 readers raise `UnsupportedCurrencyError` (*"Order is priced in EUR;
this build only handles USD."*) for any non-USD amount; the 3.2.0 readers convert with a fixed rate
table. The existing
trusted harness (`byte_shape_v1`) runs them unchanged. This is schema-at-tag decoding, not the
.NET/Kotlin binaries, and is labeled as such.

## Demo story

> "Undo the local-currency checkout, but keep the accounting fix for orders without a shipping address."

1. Naive plan: checkout → 3.1.0 and fraud-detection → 3.1.0, keep accounting 3.2.0. Startup GREEN,
   but fraud-detection 3.1.0 FAILS on every non-USD order → **BLOCKED**. Witness:
   `Plan → Deployment fraud-detection → 3.1.0 → consume_orders → orders ← orders-0@… (local-currency) → written by checkout 3.2.0`.
2. Alternative: roll back checkout only (or keep checkout 3.2.0 with `localCurrencyCheckout`
   off) and keep both consumers on 3.2.0 → **BOUNDED_PASS**.
3. "Roll back the recommendation ranking change" → recommendation 3.1.0, no state read → quick pass.

## Changes

1. `fixtures/astronomy-shop/` — `releases/*` (8 release dirs: release.json, CHANGELOG.md, codec.py),
   `payloads/*.bin`, `snapshots/*/manifest.json`, README with attribution.
2. `scripts/build_astronomy_fixture.py` — deterministic generator (byte-identical on rerun).
3. `RW_FIXTURE` (default `shop`) selects the fixture root in `rw.pipeline`; `fixture_file` re-roots
   any `fixtures/<name>/` prefix, not only `fixtures/shop/`.
4. Grounding tool text made domain-neutral (examples no longer name `cart-cache`).
5. Each fixture gets its own graph (`rw_fixture_astronomy-shop`). A hand-written 22-service
   `topology.json` and its system map were tried and removed on 2026-10-17: only 4 services are
   modeled, so the rest of the diagram was static decoration.
6. Tests: generator determinism, codec behavior (old reader fails on non-USD orders, new reader reads
   both), and a FalkorDB integration check of the three snapshot dispositions for the new fixture.

## Out of scope (later)

Public fork with real PRs/tags, live Kafka/Postgres containers, the Postgres catalog-migration
scenario, grouped batches beyond the 200-row query cap, UI copy (the UI still says "saved cart"; it is
reworked in the UI pass), MCP server.
