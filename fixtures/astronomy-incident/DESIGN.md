# Astronomy incident fixture design

Status: implemented 2026-10-19 for the demo. `fixtures/astronomy-shop` is unchanged, so results
recorded on it stay valid. Honest label wherever it is shown: *synthetic data modeled on OpenTelemetry
Demo 3.1.0 (Apache-2.0); release 3.2.0 is authored for this demo.*

## Why a second fixture

On `astronomy-shop` the hazard is one hop (old consumer, new order) and a plain LLM with every file
usually finds it. This fixture keeps the same orders (byte-identical) and adds what makes the
relationships the hard part: a second store whose incompatible rows were produced *from* the first
store's data, a third store that is unaffected, and nine services that read no retained state.

## Model

| Service | Reads | Writes | 3.1.0 | 3.2.0 |
|---|---|---|---|---|
| checkout | — | `orders` | USD orders | local-currency orders behind `localCurrencyCheckout` (default on; off = USD) |
| accounting | `orders` (`consume_orders`), `ledger` (`reconcile_ledger`) | `ledger` | USD orders only; `ledger/v1` rows only; skips orders without an address | any currency; writes `ledger/v2` for converted orders; reads v1 and v2 |
| fraud-detection | `orders` | — | USD orders only | any currency |
| cart | `cart-cache` | `cart-cache` | `Cart/v1` | `Cart/v1` (TTL change only) |
| frontend, currency, payment, shipping, email, ad, quote, recommendation | — | — | stateless | stateless |

Retained data in `snap-001`: 40 `orders` (24 USD by checkout 3.1.0, 16 local-currency by checkout
3.2.0); 37 `ledger` rows (21 `ledger/v1` by accounting 3.1.0 — the three USD orders without an
address were skipped by its bug — and 16 `ledger/v2` by accounting 3.2.0), each with
`derived_from: [<order record id>]`; 20 `cart-cache` carts.

| Snapshot | Difference | Expected |
|---|---|---|
| `snap-001` | complete | see plans below |
| `snap-002-partial` | `ledger` coverage PARTIAL | NEEDS_EVIDENCE (`COVERAGE_INCOMPLETE`) for any plan |
| `snap-003-orphan` | plus one ledger row from an operator replay script (no writer, no format, no source) | NEEDS_EVIDENCE (`WRITER_UNKNOWN`, `FORMAT_UNKNOWN`) |

## Expected outcomes (derived from the model above, not from runtime output)

| Plan (snap-001) | Obligations | Expected |
|---|---|---|
| accounting 3.1.0 + fraud-detection 3.1.0 | 40+37 (accounting) + 40 (fraud) + 20 (cart) = 137 | BLOCKED, 48 FAIL: 16 orders × 2 readers + 16 `ledger/v2` rows |
| checkout 3.1.0 + accounting 3.1.0 + fraud-detection 3.1.0 | 137 | BLOCKED, same 48 FAIL |
| checkout 3.2.0 with `localCurrencyCheckout` off, all else current | 137 | BOUNDED_PASS |

## Demo story

> "Japanese shoppers are seeing wrong totals since 3.2.0. Roll back accounting and fraud-detection to
> 3.1.0, their currency conversion is the suspect. Leave checkout alone."

1. The literal plan starts GREEN everywhere but is BLOCKED in two stores.
2. The 16 failing ledger rows were written by accounting 3.2.0, but `DERIVED_FROM` traces each to a
   local-currency order written by checkout 3.2.0 — the service the operator said to leave alone. All
   48 failures share that root writer.
3. Trusted code queries the failing records' origins and includes that evidence in the alternative
   context; the agent can also call `trace_data_origin` explicitly. In the saved demo conversations,
   the agent asks about changing the service the operator excluded. The operator answers with the
   declared flag-off strategy and requires the newer readers to stay. After that answer,
   it can propose keeping every service on 3.2.0 with `localCurrencyCheckout` off. Rechecked:
   BOUNDED_PASS. A human confirms scope and may approve the local simulation. Turning off the flag
   stops new local-currency writes; it neither repairs retained bytes nor proves the totals correct.

Lineage is evidence for the agent and the explanation. The disposition still comes only from probe
receipts. Readers are stdlib Python models of each release's decode step, not the upstream binaries.
