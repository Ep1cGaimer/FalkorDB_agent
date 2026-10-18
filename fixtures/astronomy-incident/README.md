# fixtures/astronomy-incident — SYNTHETIC FIXTURE

SYNTHETIC FIXTURE — modeled on the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo)
("Astronomy Shop") at tag 3.1.0, Apache-2.0. Release 3.2.0 is authored for this demo and is not an
upstream release; the accounting ledger reconcile route is modeled for this fixture. Every payload is
generated test data. Regenerate with `python scripts/build_incident_fixture.py` (byte-identical).

Twelve services run 3.2.0. Three stores hold retained state, and data flows across two hops:

```
checkout 3.2.0 --writes--> orders (Kafka)  --read by--> accounting, fraud-detection
accounting     --writes--> ledger (Postgres) --read by--> accounting (reconcile_ledger)
                           each ledger row is derived_from the order it booked
cart           --writes--> cart-cache (Valkey) --read by--> cart
```

checkout 3.2.0 charges shoppers abroad in their own currency (flag `localCurrencyCheckout`, default
on). accounting 3.2.0 books those orders as `ledger/v2` rows that keep the original amount and rate.
The 3.1.0 readers of accounting and fraud-detection only handle USD orders, and accounting 3.1.0 only
maps `ledger/v1` rows. Design, story and expected outcomes: [DESIGN.md](DESIGN.md).
