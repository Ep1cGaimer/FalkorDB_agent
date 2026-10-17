# Independent fixture oracle

`dispositions.json` contains eight synthetic cases and 34 enumerated obligations. It is evaluation data, not a runtime input or permission to apply a plan.

## Method

Read `AGENTS.md`, `docs/CONTRACTS.md`, the GapKind names, and the release declarations, codecs, changelogs, snapshot manifests and retained payload bytes under `fixtures/shop/`. For each candidate fleet, enumerate every declared reader route against every listed record in its read store. Both services have one ALL_KEYS route reading cart-cache: cart uses load_saved_cart/read_cart and checkout uses price_saved_cart/read_cart_for_pricing. Thus each case has four obligations except G, which has six. Flags affect future cart writes, not these readers or their obligations.

Hand-read codec control flow against the exact bytes, then confirm the ten distinct reader/payload combinations through `.venv\Scripts\python.exe -I fixtures/shop/harness/run_reader.py <codec_path> <entry>` with binary stdin. All ten matched: eight PASS exits (0), and two FAIL exits (10), both ValueError with `unsupported saved-cart format 'cart/v2'`. All seven payload references across the three manifests matched their declared SHA-256 hashes. No probe produced UNKNOWN. Reusing this prediction across cases does not authorize runtime receipt reuse across plans or snapshots.

Apply precedence after enumerating evidence gaps: any applicable FAIL means BLOCKED; otherwise any gap means NEEDS_EVIDENCE; otherwise BOUNDED_PASS. Gap rows are deduplicated by snapshot/store or snapshot/store/record, not repeated per affected reader. Partial coverage preserves the listed obligations but leaves additional real-store obligations unknown. Unknown writer/format metadata never removes a record from the inventory and never turns a successful byte read into probe UNKNOWN.

The JSON uses `(service, version, route_id, store_id, record_id)` within each fixture/snapshot.
These are evaluation keys, not production receipt identities. Predictions assume faithful graph
import, no truncation or additional missing edges, fresh snapshot evidence and one applicable
receipt per obligation. Runtime receipts must bind the exact plan/source/snapshot/reader/route/record/probe/environment identities required by the contracts. Null manifest format remains literal UNKNOWN in binding even when payload inspection reveals a fmt field. This evaluation neither creates nor validates runtime receipt hashes.

## Full identity migration and variant (issue #24)

All 34 baseline rows now include literal route/store IDs. The migration read each release's sole
route declaration and hashed its directory using the documented identity rule: sorted
`[[relative_path, "sha256:" + sha256(file_bytes)], ...]`, canonical JSON (sorted keys, compact
separators, UTF-8), then the first 16 hex characters of that JSON's SHA-256. The release ID is
`release:<service>:<short-hash>`, the route ID is `route:<release-id>:<declared-route-name>`, and the
store ID is `store:<declared-store-name>`. No runtime graph or verification output supplied an ID
or expected outcome. Baseline predictions, dispositions, gap kinds and request-fit labels are
unchanged. Readers validate nonempty identity fields and full-key uniqueness before converting
oracle rows to sets/dicts; prediction indexing rejects conflicts for a snapshot/key.

`obligation_identity.json` adds independently authored cases I (cart 1.4, BLOCKED) and J (cart 1.5
with basket_v2 disabled, BOUNDED_PASS), both with checkout 2.1. Apply the checked overlay in
`tests/fixtures/obligation_identity/` to a temporary shop copy before any consumer reads it.
Each candidate has seven obligations: two cart routes over the two cart-cache records, one cart
route over an archive record, and two checkout pricing obligations. Coverage, writer and format
metadata are complete. The archive reuses `saved-cart-2002` with different bytes.

Predictions were authored by inspecting the codec branches and payload bytes: cart 1.4's
`read_cart` rejects cart/v2, `inspect_cart` accepts cart/v1 and cart/v2, and `read_archive` accepts
only `cart-archive/v1` with `archived=true`. Cart 1.5's normal and inspection routes both accept
the saved-cart formats. Checkout 2.1's pricing reader accepts both. Thus only case I's
`load_saved_cart`/cart-cache/2002 obligation fails. Real bounded harness calls confirm all 14
predictions through the offline scripted control, independently of runtime verdicts. Acceptance
tests then compare those authored predictions with actual receipts, including exact failing keys.

Canonical overlay cart release IDs (the unchanged baseline changelogs are included in hashing):

| Release | ID |
|---|---|
| cart 1.4 | `release:cart:fa7b26506599d241` |
| cart 1.5 | `release:cart:a66fbf2097de584d` |

The overlay manifest SHA-256 is
`21b6770420150e8a3582bccfe1fd42692de78c398d39de8627227767cfe0d5d4`;
the archive payload SHA-256 is
`f587c495b4d1451a327c4b7148ab5d8d6b841f453bf2d43836a22369c23a1bb3`.
The full graph/SQL/scorer integration compares literal expected IDs against IDs independently
derived from the copied bytes, and checks payload hashes before harness execution. No production
schema, snapshot enum, provider call or fixture generator change is needed.

## Independence

For the original baseline authorship, no verification, graph, probe, grounding or other implementation module under `src/rw/` was read, imported or executed. The contracts.py lookup targeted GapKind; the initial contextual text search also displayed adjacent schema declarations inadvertently. Those adjacent declarations were not used to derive outcomes. Only the fixture harness and fixture codecs were executed, with isolated Python; no application module or database was used. Expected results come from fixture source behavior and the written contract, not an implementation's output. That original review authored only the two baseline files in this directory; the issue #24 identity migration and variant are described above.

## Request interpretation and limits

Changelog citations use repository-relative paths and 1-based inclusive line spans, with exact excerpt text. They describe release behavior, not dynamically verified UI or receipt arithmetic. Checkout 2.1 retains the receipt correction and basket headings together. The reader probe does not call receipt_total or render headings.

For A, B, E, F and G, basket_rollout_undone is partial: cart-side rollout/new cart/v2 writes are undone, while checkout 2.1 retains headings for the saved cart with baskets. D is false. C and H are true only in the sense of selected cart/checkout release behavior: they remove checkout 2.1 too, lose the correction and are blocked by retained cart/v2 bytes. No case migrates or erases that retained record. None proves a fully working end-to-end basket undo while keeping the correction. A narrower cart-only interpretation would call the partial cases true; that scope requires clarification, not an invented hybrid artifact.

BOUNDED_PASS is modeled byte/shape readability only. It does not establish business semantics, rounding correctness, rendering, unmodeled keys, concurrent writes, operational safety, request satisfaction or action approval. E and F cannot enumerate unseen records. G preserves manifest provenance uncertainty despite successful probes. Bundle metadata does not require an atomic bundle rollback. These cases do not measure baseline performance or benchmark gains.

## Contract ambiguities

- The obligation-binding section says every field below forms the canonical tuple, but does not actually enumerate that tuple there. Exact binding fields cannot be independently reconstructed from this prose. The requested simplified oracle is conditional on correct applicable receipts, not a substitute for the missing tuple specification.
- FORMAT_UNKNOWN is a GapKind name but is omitted from the prose list of gap examples. G treats it as a gap under the general any-gap rule; WRITER_UNKNOWN independently establishes NEEDS_EVIDENCE, so the disposition is unambiguous.
- The contract mentions a missing IN_STORE edge as a gap, but the GapKind names provide no dedicated name for it. These fixtures do not specify a missing IN_STORE edge, so no invented classification is added.
- The harness classifies a non-dict return as FAIL, while the prose table explicitly describes reader exceptions as FAIL and a returned dict as PASS without specifying non-dict returns. None of these codecs exercises that ambiguity.
- The behavioral phrase "undo the basket rollout" does not specify whether retained checkout headings must disappear. This affects request-fit labels, not byte-readability dispositions.
