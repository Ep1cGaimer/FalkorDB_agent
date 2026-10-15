# fixtures/shop — SYNTHETIC FIXTURE

SYNTHETIC FIXTURE — every byte here is generated test data, not real product data.

A tiny two-service shop used by RollbackWitness tests.

## Layout

```text
releases/<service>-<version>/release.json   declared facts (no compatibility verdicts)
releases/<service>-<version>/codec.py       real reader/writer code for that build
releases/<service>-<version>/CHANGELOG.md   human release notes (source excerpts)
snapshots/<name>/manifest.json              deployments, stores, coverage, inventory
payloads/<record_id>.bin                    retained bytes, produced by the generator
harness/run_reader.py                       trusted probe harness (byte_shape_v1)
```

Services: `cart`, `checkout`. One store: `cart-cache` (kind `kv-cache`).

## Rebuild

```text
.venv\Scripts\python.exe scripts\build_fixture.py
```

The generator loads the release writer codecs by path, regenerates every payload,
and rewrites the manifests with matching `payload_hash` values. It is deterministic:
running it twice produces byte-identical files.

## No expected outcomes here

This directory holds only inputs and declared facts. It contains no compatibility
verdicts, no expected results and no disposition labels — those are produced by
trusted code at runtime and are never read back from here.
