# RollbackWitness — four-minute demo

Read this conversationally, around 140 words per minute. Leave short pauses for the result,
graph and changed flag. The narration is about 530 words: roughly 3:45 of speech plus pauses;
rehearse once against the screen for a four-minute cut.
Use the recording cues below rather than reading the interface aloud.

## Narration

### 0:00–0:25 · The problem

Imagine you're on call. A release goes wrong, so you roll the code back. The old services start,
the health checks are green, and everything looks fine.

But the data hasn't rolled back with them. The newer release has already written records that
the older readers don't understand.

That's the problem RollbackWitness checks before you make the change.

### 0:25–0:55 · The request

This is a synthetic shop with twelve services and three stores: orders, an accounting ledger,
and saved carts.

The incident report says Japanese shoppers are seeing wrong totals. I suspect accounting and
fraud detection, so I ask to roll those two back to 3.1, and leave checkout alone.

The agent looks through version-linked release notes and code, cites what it used, and proposes
actual builds that exist. I review that fleet and confirm the scope.

### 0:55–1:25 · Startup is not enough

Here's the catch: those builds start successfully. But RollbackWitness doesn't stop at startup.

FalkorDB connects the proposed deployments to their reader routes, the stores they read, and the
records still in those stores. That produces 137 reader-and-record checks.

The checker runs the real fixture readers against the retained bytes. Forty-eight checks fail,
across orders and the ledger. The proposed rollback is blocked.

### 1:25–2:15 · Follow the evidence

Let's follow one of those failures. This older accounting reader expects ledger version one,
but this saved row uses version two. Its receipt shows the reader error, tied to that exact
release and payload.

Now look one step further back. These sixteen incompatible ledger rows were produced from
orders written by checkout 3.2. Checkout is the service I said to leave alone.

That's the useful connection here: the immediate writer is accounting, but the upstream data
comes from checkout. The graph gives us an inspectable path across those stores, and trusted
code sends that evidence back into the agent's next decision.

This establishes a rollback compatibility hazard. It doesn't prove what caused the incorrect totals.

### 2:15–3:00 · Change the proposal

I ask for an alternative. Because changing checkout would go beyond my original request, the
agent asks for permission.

I respond with a different approach: turn off checkout's declared local-currency flag, and keep the newer readers.
The revised proposal keeps every service on 3.2 and changes that one flag. There's no invented
hybrid release.

That stops new local-currency writes. It doesn't convert or repair the records already stored.
Keeping the compatible readers is what lets those existing records remain readable.

### 3:00–3:35 · Check again

I confirm the revised scope, and the checker runs again. This time, all 137 checks pass.

The result is called bounded pass deliberately. It covers the modeled byte and shape
compatibility we've checked here, not overall production safety or correct business arithmetic.

Missing coverage or unresolved evidence would produce needs evidence instead. The system
doesn't treat missing checks as successful checks.

### 3:35–4:00 · The boundary

Finally, approval stays with the human. I can approve a local simulation, and repeating it
doesn't apply it twice. This demo never deploys anything.

The agent interprets the request. FalkorDB determines the connected obligations and exposes the
evidence path. The checker proves the modeled reads. Together, they turn a plausible rollback
into a proposal we can actually inspect.

## Recording cues

| Time | Screen and action | Hold long enough to see |
|---|---|---|
| 0:00 | Open the branded investigation workspace. | Logo and product name; no terminal or private configuration. |
| 0:25 | Show the first incident sample, then start investigation. | Synthetic label, twelve services and the operator's “Leave checkout alone” constraint. |
| 0:45 | Open cited sources and review the proposed fleet. | Two consumers change to 3.1.0; checkout stays 3.2.0. |
| 0:55 | Confirm scope; cut only waiting time if necessary. | Green startup, **BLOCKED**, 137 checks, 48 failures. |
| 1:25 | Open connected evidence; select a failing ledger cluster, then a ledger row. | Accounting 3.1.0 reader, `ledger/v2`, exact record and failing receipt. |
| 1:45 | Close the receipt if it obscures the graph; show the dashed lineage edge and origin callout. | Sixteen ledger rows → orders → checkout 3.2.0; one `DERIVED_FROM` hop. |
| 2:15 | Request the alternative. Show the clarification before answering. | Permission to touch checkout is requested explicitly. |
| 2:35 | Submit the approved flag change, review the new fleet, confirm scope. | All builds remain 3.2.0; `localCurrencyCheckout: false`. |
| 3:00 | Show the second result and candidate comparison. | **BOUNDED_PASS**, 137 checks, zero failures. |
| 3:35 | Click human approval, then local simulation. Repeat simulation if enabled. | Local-only label and unchanged/idempotent result. |
| 3:55 | Finish on the branded result workspace. | Product name and the evidence-backed alternative. |

## Adapt to what actually happens

- **Recorded model output:** keep **Replay · not live** visible. Replace “the agent looks” with
  “I'm replaying a saved agent conversation; the graph checks and readers run again.” Do not
  present playback as a new model call.
- **Agent proposes the flag change directly:** show the exact proposal and obtain scope
  confirmation. Replace the permission paragraph with “This changes checkout, so I review and
  explicitly confirm that broader scope.” Do not claim a clarification occurred.
- **Provider or evidence failure:** show the refusal briefly, then restart in labeled replay mode.
  Never splice a successful result onto an unsuccessful live attempt as if it were one run.
- **Slow calls/checks:** trim waiting time and add a small “Waiting time shortened” caption.
  The timestamps above are an editing target, not a claim about execution speed.

## Optional comparison inserts

Keep these out of the core four-minute take unless replacing an equivalent-length section.

**Plain-text call, about 15 seconds:** “This gives the same live model the fixture as text in
one call, without reader probes. It may identify the same hazard. The comparison is illustrative;
the tools and budgets differ, so this isn't a benchmark of graph superiority.” Only show its actual
answer and claim-check counts. A replayed investigation cannot run this same-live-model comparison.

**Remove lineage, about 15 seconds:** “On a disposable graph copy, removing these lineage edges
leaves the 48 reader failures intact, but removes the established upstream paths. Compatibility
comes from the receipts; lineage explains where that retained data came from.” Keep the original
graph and payloads intact. Use the measured relationship-removal result, not a mock animation.

**SQL question:** the existing equal-facts SQL control ties on obligation sets. The claim is that
connected queries drive the investigation and provide inspectable paths, not that SQL cannot do it.
