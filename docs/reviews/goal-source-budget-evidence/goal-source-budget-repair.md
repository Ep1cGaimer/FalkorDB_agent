# Source-byte budget repair and current build

The current199-file working-source build rejects oversized source payloads before
fetching them in the tested retrieval paths. Ten targeted regressions passed;
the independent revalidation passed8/8. Full staged parent QA passed **1,244
tests**, with **6 missing-artifact skips** and **3 live exclusions**, in250.75
seconds. All199 source hashes matched before/after. This is development evidence;
full T0–T11 acceptance remains incomplete.

The original independent audit configured one byte but observed159,984 source
payload bytes before rejection. Blob reads now inspect immutable object size
before requesting payload. Diff and patch-ID reads reserve complete changed
old/new blob inputs before generation. Rejected reservations leave the consumed
counter unchanged; successful diff reservations are conservative and shared
across the request. Empty/exact-fit blobs, root/deletion diffs, filenames with
spaces/newlines/Unicode and repeated operations are covered. This bounds the
measured source payload/inputs, not all Git metadata output, OS disk reads, memory
or an operating-system wall-clock deadline.

The [independent repair report](goal-bounded-retrieval-source-revalidation.md)
preserves the original failure and exact before/after payload observations. The
[earlier pagination audit](goal-bounded-retrieval-audit.md) and
[index recovery audit](goal-index-recovery.md) concern their original198-file
source pin; they were not silently relabeled current after this repair. Current
full QA covers their applicable regression tests, not every archived experiment.

The fresh configuration-only Flask trial on the199-file build selected public
tag3.1.2, commit `2c1b30d0503cfb064f1cb252e6614a06915a362a`, and imported5,440
reachable commits. It selected24 Python files plus4 metadata files at the tip,
with an independently matching file map and zero extraction errors. Production
import took12.25 seconds; total recorded clone/setup/import work took18.40
seconds. The independent author reported no prior Flask source-body inspection;
the harness inspected Git/tree metadata and production ingestion parsed source.
No core or adapter changes were required. Cleanup removed the owned graph and
container. This is supplementary onboarding evidence, not a replacement for the
unsigned Requests/Click evaluation contract or a full T1 pass. The earlier Click
trial retains its historical198-file pin.

After the repair, the owned demo server was restarted on8127 with the same fixed
database port55688. A focused smoke passed fresh natural-language investigation,
real two-hop retrieval, all citations, fixed/reverted states, truncation and the
missing-symbol gap. Actual browser checks opened hash-verified TimedSerializer
source and repeated the boundaries, explicit replay and return to live retrieval.
One harness assertion expected the literal missing symbol name, while the UI
correctly displayed “The requested symbol cannot be resolved uniquely.” That
original assertion mismatch and a separate observation of the actual gap remain
recorded. This targeted recheck does not relabel the earlier three full rehearsals
as199-file runs or claim a narrated human rehearsal.

Candidate evaluation corpora were also prepared for all five declared snapshots
of Requests and Click. Exported sources/history are identical inputs available to
both arms; no held-out question or answer was read. The compact plaintext forms
contain65,272,825 bytes for Requests and77,589,283 for Click. Exact model-token
counts for these new serializations remain unmeasured. Earlier development counts
cannot be substituted for their changed identities/root sets. The readiness
capture preserves exact prompts/tool contracts and enumerates the remaining
signature blockers; it is not a frozen plan or a successful quality comparison.

The deadline outcome is explicit: the supported primary demo was ready before
18:45 IST; full secondary acceptance was **not completed by19:30 IST**. Remaining
work includes a signed contract, provider availability, held-out scoring/paired
comparisons, complete scale/fault/boundary matrices, independent reproduction and
official event deliverables. No full acceptance, advantage or runtime compatibility
claim is made. No commit or push was made; the handoff commit remains canceled.
