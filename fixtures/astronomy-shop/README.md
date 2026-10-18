# fixtures/astronomy-shop — SYNTHETIC FIXTURE

SYNTHETIC FIXTURE — modeled on the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo)
("Astronomy Shop") at tag 3.1.0, Apache-2.0. Release 3.2.0 is authored for this demo and is not an
upstream release. Every payload is generated test data.

Scenario: checkout 3.2.0 charges shoppers in their own currency (EUR, GBP, CAD, JPY), so Kafka
`orders` messages are no longer all in USD. accounting and fraud-detection 3.2.0 convert any of these
currencies; their 3.1.0 readers only handle USD and fail with
`UnsupportedCurrencyError: Order is priced in EUR; this build only handles USD.` Design and upstream sources:
[docs/plans/astronomy-shop-fixture.md](../../docs/plans/astronomy-shop-fixture.md).

## Layout

```text
releases/<service>-<version>/release.json   declared facts (no compatibility verdicts)
releases/<service>-<version>/codec.py       stdlib model of that build's Kafka read/write step
releases/<service>-<version>/CHANGELOG.md   release notes (source excerpts)
snapshots/<name>/manifest.json              deployments, the `orders` topic, coverage, inventory
payloads/<partition>@<offset>.bin           retained message values (real protobuf wire bytes)
```

Probes use the shared trusted harness `fixtures/shop/harness/run_reader.py` (`byte_shape_v1`).

## Use

```text
.venv\Scripts\python.exe scripts\build_astronomy_fixture.py      # deterministic rebuild
$env:RW_FIXTURE = "astronomy-shop"                                # PowerShell; default is shop
.venv\Scripts\python.exe scripts\serve.py
.venv\Scripts\python.exe scripts\investigate.py --fleet checkout=3.1.0 --fleet fraud-detection=3.1.0 --confirm-as you
```

## No expected outcomes here

This directory holds only inputs and declared facts; dispositions are computed by trusted code at
runtime. Test expectations live in `tests/test_astronomy_fixture.py`.
