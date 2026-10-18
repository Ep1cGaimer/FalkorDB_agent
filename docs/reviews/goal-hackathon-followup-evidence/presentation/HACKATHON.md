# Hackathon demo — 18 October 2026

Primary deadline: **18:45 IST**. Demo delivery and final fixes: **19:30 IST**.
The requested secondary deadline is19:30 IST; full secondary acceptance is still unvalidated and remains required.

Open **http://localhost:8127**. The current isolated demo database is the owned
`rw-hackathon-demo-20261018` container, mapped to host port55688. Existing user
services on6379 and6382 are separate and untouched.

## Three-minute walkthrough

1. **Explore a real dependency chain.** ItsDangerous is real inspected development
   source, pinned at `096c8d42545d3b68ea21a4f890fb2b2d8979c0bd` (2.2.0).
   Follow URLSafeTimedSerializer → TimedSerializer → Serializer. Solid edges are
   parsed; dashed edges are static inference. Do not claim runtime MRO execution.
2. **Click a citation.** Show verified source lines, full commit and content hash.
   Open the exact revision on GitHub if network is available. Local source does
   not depend on external network access.
3. **Inspect the fix, then catch its revert.** This is explicitly synthetic Git
   history. The guard is present at `fixed`; it is absent at `reverted` despite
   the fix being an ancestor. Ancestry alone cannot establish current presence.
4. **Exhaust the page.** Only one relationship is returned. The response says
   truncated rather than concluding no other dependency exists.
5. **Missing evidence.** NoSuchDemoSymbol produces a named gap, no invented source.

Fresh question: enter `What does TimedSerializer depend on?` or
`Where is TimestampSigner defined?`. This view performs **live deterministic graph retrieval**, not
an LLM-generated conversation. Runtime compatibility and comparative advantage
remain unverified. The full T0–T11 contract has not passed.

## Launch and reset

Use Python3.12 with project dependencies installed. This workstation's known
interpreter is `/tmp/rw-mcp-compat/bin/python`.

```sh
# Start the existing owned database if it is stopped:
docker start rw-hackathon-demo-20261018
# Refresh the two dedicated demo indexes; retain existing recordings:
RW_FALKORDB_PORT=55688 /tmp/rw-mcp-compat/bin/python scripts/hackathon_demo.py setup
# Focused smoke and backup generation:
RW_FALKORDB_PORT=55688 /tmp/rw-mcp-compat/bin/python scripts/hackathon_demo.py smoke
# Serve on the dedicated demo port:
RW_FALKORDB_PORT=55688 /tmp/rw-mcp-compat/bin/python scripts/hackathon_demo.py serve --port 8127
```

If creating this dedicated container for the first time, use a fixed host port:

```sh
docker run -d --name rw-hackathon-demo-20261018 --memory=2g \
  -p 127.0.0.1:55688:6379 \
  falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6
```

Do not use an automatically assigned host port for this launch configuration:
Docker can change it on restart. The final recovery check retained the explicit
55688 binding and verified a new live investigation after restart. Its failed
pre-repair attempt is preserved in `recovery-followup.json`.

For another machine, create an isolated FalkorDB container on an available explicit
port, use that port in `RW_FALKORDB_PORT`, and install dependencies from
`pyproject.toml`. The development bare clone must exist at `artifacts/repos/itsdangerous`:

```sh
git clone --bare https://github.com/pallets/itsdangerous.git artifacts/repos/itsdangerous
```

Every investigation saves an actual query trace and response under
`artifacts/hackathon-demo/runs/`. Import receipts and focused smoke receipts are
stored beside them. The synthetic trap is generated using ordinary Git commands
by `setup`; it is never presented as a real-repository holdout.

## Recovery

The **Open recorded backup · NOT LIVE** button explicitly loads the last saved
real dependency response and verified source snapshots. It does not silently
substitute for a failed live request. Source snapshots are included so the backup
can work with the database offline while this local web server remains running.
A live request failure stays visible. Start the database and retry deliberately
when returning to live mode.

Browser automation became available through the Helium native application. Three
consecutive complete browser-flow rehearsals passed after separate index resets;
see [primary status](STATUS.md). These automated sequences are not a narrated
human presentation or video. The HTTP smoke is recorded separately.
