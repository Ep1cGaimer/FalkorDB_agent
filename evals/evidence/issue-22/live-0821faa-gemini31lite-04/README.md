Synthetic fixture evidence for issue #22.

Verify: `python evals/comparison_evidence.py verify BUNDLE`

Rescore without network or credentials: `python evals/score_controls.py --bundle BUNDLE --json /tmp/scores.json`

All scoring fixture bytes and expectations are included. Source hashes identify collection inputs; Git SHA plus dirty inventory records provenance. Exact model requests, parsed tool arguments and numeric usage are retained. Provider envelopes, account identifiers, credentials and local paths are excluded. Missing usage remains unknown. Clarification appropriateness is ungraded. The legacy arm compares broader workflows. SQL can independently reconstruct the ablated pairs.

Superseded protocol: final regression testing found that the compact context omitted explicit canonical store IDs required by the legacy probe contract. These nine completed observations are retained, but are excluded from issue #22 acceptance and the primary headline. The corrected protocol is collected separately; no model answers were repaired.
