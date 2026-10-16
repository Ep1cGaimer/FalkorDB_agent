# Rollback review workspace

The interface follows the owner's October 16 visual references: a pale workspace shell,
narrow sidebar, white panels, fine dividers, compact tables and restrained blue actions.
Color communicates result semantics. No external fonts, UI libraries, CDNs or frontend build
are required; FastAPI serves native ES modules and CSS.

First-time visitors get a one-sentence explanation of rollback and short captions beside the
decisions. Plain labels describe running services, saved shopping carts, the basket feature's
On/Off state, and saved-data checks. Small keyboard- and touch-accessible info buttons explain
versions, flags, formats, coverage, run modes and verdicts on demand; there is no onboarding
dashboard or forced tour. These explanations use the existing dialog/navigation behavior.
Friendly format labels describe the authored fixture only and leave unknown formats unknown.

## Presenting an investigation

The opening screen shows the snapshot's current releases, inventory completeness and retained
records. It omits counts, snapshot timestamps and store metadata that do not change the decision.
The default request
explicitly selects the build before the basket rollout, so the checker can expose the older
reader's incompatibility. Live grounding may still ask a clarification; it is not forced into
a predetermined result.

Confirm the proposed scope to run graph queries and real reader probes. The review then leads
with the trusted disposition and contrasts startup with retained-state reads. The connected
evidence diagram shows the actual read error immediately; the diagram and matrix open the exact
probe receipt. Source citations and raw probe evidence remain inspectable. Raw query and model
tool-call logs stay in the API evidence, rather than appearing as product UI.

An alternative receives its own scope confirmation and verification. The previously selected
record stays in focus across the comparison, making it clear whether the same retained data
is readable under the new candidate. Human approval and local simulation remain separate
actions, available only for a server-returned BOUNDED_PASS. The pass limit is visible.

One review contains the proposed fleet, trusted result, connected evidence, reader/record matrix
and eligible next action. A compact candidate selector compares two independently checked plans
without duplicating the fleet or result screen. The sidebar reopens actual prior reviews; there
is no second history table, Environment page, tutorial, model-info card, profile or activity feed.

Demo setup contains only live/replay selection, the recording and retained-data scenario.
Recorded clarification answers are selected from transcripts bound to the exact current request
and question, without guided-input controls. Replay remains explicitly labeled.

The visible Back button and browser Back/Forward share the same view history. Entries retain
the request draft, demo setup, selected candidate and record, open dialog and scroll position.
Closing a setup dialog keeps its edits. Reload restores the view and fetches the investigation
from the local server; navigation never reruns checks or simulation. A direct investigation link
can return to its request through the visible Back button without leaving the app. Navigating
during an in-flight action waits for the action to finish, then restores the requested view.
Investigation evidence remains server-held; a server restart still clears its in-memory registry.

## Decision audit

| Component | Decision value | Treatment |
|---|---|---|
| Proposed releases and flags | Establishes exactly what will change and what remains | Keep |
| Disposition, startup/read contrast and actual failure | Establishes whether this fleet is eligible and why | Keep |
| Graph witness, exact receipts and source citations | Supports inspection of the decision | Keep; detailed identities expand on demand |
| Inventory/provenance gaps and bounded-pass limit | Explains uncertainty and the limits of passing checks | Keep |
| Candidate comparison | Shows whether another configuration changes the outcome | Keep one compact selector |
| Operator and approver text fields | Arbitrary names did not authenticate or authorize anyone | Remove |
| Check-summary metrics | Repeated the verdict and matrix | Remove |
| Repeated environment, Evidence tab and history table | Duplicated facts already available in the review | Remove |
| Tutorials, activity feed, profile and model/tool logs | Did not help choose or verify a fleet | Remove |

The UI sends `local-ui-user` as the required API audit-origin label after explicit confirmation
and approval clicks. It is not an authenticated person's identity. The backend contract and its
scope, evidence-freshness, disposition, approval and simulation gates are unchanged. Names are
not moved into another form. Repeating a simulation is a secondary action inside its receipt.

## Files

| File in `src/rw/static/` | Responsibility |
|---|---|
| `index.html` | Semantic application shell and entry point |
| `styles.css` | Design tokens, layout, components and responsive rules |
| `app.mjs` | Investigation state, API actions, rendering and focus restoration |
| `views.mjs` | Fleet, results, comparison, clarification and minimal demo setup |
| `evidence.mjs` | Connected path, matrix, source evidence and receipt inspector |
| `explanations.mjs` | Contextual definitions and plain labels for the authored demo |
| `model.mjs` | Pure receipt matching, matrix identities, counts and replay selection |
| `api.mjs` | JSON transport and structured error handling |
| `dom.mjs` | Safe DOM construction, inline icons and shared view primitives |

All returned text is inserted as text nodes. The browser does not compute a disposition or
grant eligibility. Receipt display requires the complete bound tuple and uses the same result
precedence as the checker. Matrix identities retain deployment, route, store and batch identity.

`GET /api/snapshots` reads the fixture manifests without connecting to FalkorDB or invoking
grounding. `/static` serves browser assets from the existing FastAPI app.

## Verification

Normal launch remains `.venv/Scripts/python.exe scripts/serve.py` (port 8000). Restart an
already-running server after this refactor so it picks up the static mount and snapshot route.

The non-live Python suite includes asset content-type checks, fixture-context checks and Node
tests of the actual browser data module. The standalone browser acceptance check uses an
isolated headless Chromium profile and a visibly labeled deterministic grounding adapter;
FalkorDB, reader probes, verification, approval and simulation are real.

```powershell
# With FalkorDB running; use two terminals:
.venv/Scripts/python.exe tests/ui/serve_fixture.py
node tests/ui/check.mjs
```

The QA server uses port 8002, its own graph and a temporary simulation ledger. Stop it with
Ctrl+C to clean up the graph. `UI_BROWSER_BINARY` can select another Chromium executable;
`UI_BASE_URL` changes the target URL. Node 22+ is needed for the browser check's native WebSocket.
Screenshots are generated under `artifacts/screens/decision-review/` (git-ignored). The QA adapter
calls no model and is not enabled by the normal application server.

The browser check covers Back/Forward, the visible Back control, reload with an open receipt,
candidate restoration, direct links, navigation during checks, failure inspection, the alternative, bounded pass, approval,
idempotent simulation, partial inventory, orphan provenance, clarification, saved replay when
available locally, and mobile navigation. It checks that name fields and removed panels stay
absent, that explicit clicks still create separately bound confirmations and approvals, and that
there are no browser exceptions or failed resource requests. Saved replay is optional because
transcripts are local artifacts.
Contextual-help checks cover keyboard access, preservation across refresh and browser
navigation, and the guarantee that opening an explanation does not trigger an investigation.
