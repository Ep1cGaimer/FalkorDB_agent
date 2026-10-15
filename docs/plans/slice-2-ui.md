# Slice 2 UI design (agreed with the owner)

One calm, single-column incident-console screen (~1100px content width) that reads top to bottom in investigation order. No animation for its own sake; the wow is the green-startup vs red-reader contrast and the evidence path. Avoid the generic-admin look: no card on every section, no numbered wizard headers, no stock outlined badges, no hash noise.

```
RollbackWitness   Can this rollback read data the newer release saved?
SYNTHETIC FIXTURE · snapshot snap-001 · FalkorDB 6.0.2 · model: <actually answered>
──────────────────────────────────────────────────────────────────────────
REQUEST   [ Undo the basket rollout, but keep the receipt correction. ]
          (•) Live  ( ) Replay saved run ▾   [Guided demo ☐]   [ Investigate ]
AGENT ASKS (when clarification)            LIVE ● / REPLAY — not live
  "<question>"   ❝quote❞ checkout 2.1 ↗   ❝quote❞ checkout 2.1 ↗
  [ answer text ]  [ Answer ]
PROPOSED FLEET                                             candidate 1
  cart      1.5 → 1.4   CHANGE   ❝quote❞
  checkout  2.1 → 2.1   keep     ❝quote❞
  Operator [ name ] [ Confirm scope for checking ]   (not an approval)
RESULT
  BLOCKED                          (largest text on the page)
  ┌ cart 1.4 startup check ┐  vs  ┌ cart 1.4 reading retained carts ┐
  │ GREEN — build loads    │      │ FAIL — saved-cart-2002 unreadable│
  WHY — evidence path from FalkorDB (schematic chain, relationship names on edges)
  [Plan]→[Deployment cart]→[cart 1.4]→[load_saved_cart]→[cart-cache]←[saved-cart-2002 · cart/v2]→[cart 1.5]
  READER × RETAINED RECORD matrix (versions as labels; PASS/FAIL/UNKNOWN cells)
  RECEIPT drawer (selected cell): exit, error_type: message, payload/reader/obligation hashes (short, click to expand), duration
  ▸ Gaps (n)   ▸ Graph queries executed (n)   ▸ Raw probe output
ALTERNATIVE   [Ask agent for an alternative]   candidate 1 vs candidate 2 side by side
ACTION (rendered only when current plan is BOUNDED_PASS)
  Approver [ name ] [ Approve local simulation ] [ Run simulation ]   LOCAL SIMULATION ONLY
```

States: NEEDS_EVIDENCE (amber, checklist of what is missing, no action), clarification-only (ends at question), rejected proposal (plain reasons, nothing checked), provider failure ("Live model unavailable (503)" + offer replay, never silent fallback).

Visual rules: near-black text on off-white, one accent color for interactive elements, red/green/amber only for verdict semantics; one heading face + one monospace (system stacks); versions shown by default, hashes short with click-to-expand; scope confirmation and action approval worded and placed differently. Readable at 1280 and 1920.
