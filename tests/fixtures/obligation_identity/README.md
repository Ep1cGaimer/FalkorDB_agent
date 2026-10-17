# Obligation identity overlay

Copy `fixtures/shop/` into a temporary directory, then copy this overlay over it. The pytest helper
in `tests/conftest.py` does this before any importer, control or scorer reads the resulting root.
Baseline fixtures stay unchanged; the normal fixture generator does not consume this overlay.

Cart 1.4 and 1.5 declare `load_saved_cart` and `inspect_saved_cart` on cart-cache plus
`load_archived_cart` on cart-archive. The archive's `saved-cart-2002` has different bytes from the
same ID in cart-cache. Cart 1.4's normal reader rejects cart/v2 while its inspection reader accepts
it; both readers in cart 1.5 accept it. Both releases' archive reader accepts the archive payload.
The existing checkout reader and baseline changelogs remain in the copied fixture.

Expected cases I and J are authored in `evals/expected/obligation_identity.json`. See
`evals/expected/README.md` for prediction derivation, literal release IDs and payload/manifest
hashes. The tests run those predictions through real bounded harness calls, the real FalkorDB
pipeline, SQL joins and the scorer, including deliberately incomplete evidence.
