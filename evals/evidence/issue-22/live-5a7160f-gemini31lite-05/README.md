Synthetic fixture evidence for issue #22.

Verify: `python evals/comparison_evidence.py verify BUNDLE`

Rescore without network or credentials: `python evals/score_controls.py --bundle BUNDLE --json /tmp/scores.json`

All scoring fixture bytes and expectations are included. Source hashes identify collection inputs; Git SHA plus dirty inventory records provenance. Exact model requests, parsed tool arguments and numeric usage are retained. Provider envelopes, account identifiers, credentials and local paths are excluded. Missing usage remains unknown. Clarification appropriateness is ungraded. The legacy arm compares broader workflows. SQL can independently reconstruct the ablated pairs.

Primary acceptance batch: all nine conversations completed on `gemini:gemini-3.1-flash-lite`, with a 1,000-token output cap and eight-turn limit. The matched result is a 3/3 tie, with supported BOUNDED_PASS and 4/4 receipt coverage in both arms; request fit is partial. The legacy arm chose clarification three times (semantic appropriateness ungraded). See [comparison.md](comparison.md).

Collected on `5a7160f676ddab30438e141fe68594506c9ccaff`; validated/rescored on `dd8560c83b3ed315946861f045bd968500fc9584`. The later validator change permits filesystem aliases outside the bundle while rejecting internal symlinks; model inputs and evidence were unchanged. A moved copy was verified/rescored with credentials removed and network access denied.
