# Three-minute presentation

**0:00–0:20 — Problem.** “A commit in history does not prove that its fix is
still present. We connect code to its exact Git revision so you can inspect the
evidence behind an answer.” Open http://localhost:8127.

**0:20–1:05 — Real source.** Type `What does TimedSerializer depend on?`, then
Investigate. Explain that this is a supported deterministic question using live
FalkorDB retrieval. Click the first sequence button to show the two-hop
URLSafeTimedSerializer chain. “This points us from the URL-safe timed serializer
through its intermediate classes to the common serializer implementation.”
Click a citation and show the full commit, source lines and verified hash.
“Solid relationships are parsed; dashed relationships are static inference.”

**1:05–1:45 — Current presence.** Click Inspect the fix, then Catch the reverted
fix. “This small history is synthetic. The guard was added and then reverted.
The fix commit is still an ancestor, but its change is absent at this revision.”
Show the actual source alongside the status.

**1:45–2:20 — Limits.** Click Exhaust the result page, then Ask for missing
evidence. “A bounded page says that evidence was omitted. An unknown symbol
stays a gap. Neither becomes a claim that nothing else exists.”

**2:20–3:00 — Scope.** “This demo retrieves source evidence on Python and Git.
It does not establish runtime compatibility. Our comparison is unfinished, so
we are not claiming an accuracy or cost win over plaintext.” If a live operation
fails, show its error and explicitly choose Open recorded backup · NOT LIVE.
Say aloud that the result is a recording. See [claim card](CLAIMS.md) for the
measured boundaries and [launch/reset instructions](HACKATHON.md) for recovery.
