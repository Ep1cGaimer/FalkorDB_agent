# Issue #4: Groq free-tier operating choice

Issue: [Groq free-tier limits for live use](https://github.com/Ep1cGaimer/FalkorDB_agent/issues/4).

## Decision

Use the smaller evaluation budget on the existing Groq free tier. Pin the application and both sides
of a comparison to `groq:qwen/qwen3.8-27b`, cap generated completions at 1000 tokens, and run the
paired evaluation sequentially:

```dotenv
RW_GROUNDING_MODEL=groq:qwen/qwen3.8-27b
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000
```

```bash
RW_GROUNDING_MAX_COMPLETION_TOKENS=1000 .venv/bin/python evals/run_comparison.py --runs 3 --model groq:qwen/qwen3.8-27b
```

The author reported exercising this option against the project's control and product. The historical
October 16 comparison is author-reported, with no committed raw or sanitized evidence bundle. It
reports all three pairs on this profile and four recovered HTTP 429 responses across six conversations. The reported
maximum input was 6,609 tokens for the product and 5,237 for the control. No final-pair request
failed. See [the full comparison and scorer output](ISSUE_3_COMPARISON.md).

Keep the credential in the git-ignored `.env`. Do not add more simultaneous evaluations or raise the
completion cap without measuring the account's allowance. The limit is shared at Groq organization
level; a second key in the same organization does not provide an independent quota. A paid tier is
also unnecessary for the measured three-pair workload. Groq notes that some accounts have distinct
input/output limits and that the account Limits page has the exact current values: [rate-limit
documentation](https://console.groq.com/docs/rate-limits).

This profile bounds the workload; the historical report cannot guarantee that a
later live request will avoid quota exhaustion. The client reports a generic quota message, retries
transient 429s according to response headers, and preserves a failure artifact if a run cannot
continue.

## Browser check of the sanitized quota message

The backend already maps provider 429 and 413 errors to HTTP 502 with code `provider_quota` and the
fixed message:

> Live model rate limit or request size limit reached. Try replay.

`tests/test_api.py::test_provider_failure_is_sanitized` checks that organization identifiers and
usage details are absent from the API response. On 2026-10-17, the local console at
`http://127.0.0.1:8000` was opened in Chromium. The browser's `fetch` for `POST /api/investigations`
was intercepted and answered with this sanitized HTTP 502 payload, so the check did not call Groq:

```json
{
  "detail": {
    "code": "provider_quota",
    "message": "Live model rate limit or request size limit reached. Try replay."
  }
}
```

The browser displayed `Live model unavailable (502)`, the fixed quota message, and the replay action.
The alert contained no organization ID, quota usage, or key. This verifies the UI rendering path; the
API test separately verifies that the backend removes provider-specific details before returning the
payload.

To repeat the browser check without spending provider quota, open the console, paste this in its
developer console, then click **Investigate**:

```javascript
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (url.includes("/api/investigations") && (init.method || "GET").toUpperCase() === "POST") {
    return new Response(JSON.stringify({detail: {
      code: "provider_quota",
      message: "Live model rate limit or request size limit reached. Try replay."
    }}), {status: 502, headers: {"Content-Type": "application/json"}});
  }
  return originalFetch(input, init);
};
```

## Acceptance status

The choice is documented; the browser check above is an author-reported observation of the earlier UI,
not a committed browser trace or validation of later UI revisions. The issue remains open for
maintainer review; no issue closure was performed. The selected free-tier account can still return
429 or 413 if its live allowance changes or a request grows beyond the tested profile.
