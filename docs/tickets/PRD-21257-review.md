# PRD-21257 · Code review

Status: frozen @ cd17960330e8b24c98f91ad60a5ed9981510ddcc

## Round 1 · 2026-11-02 · reviewed dev/PRD-21257 @ 2bc3a1f (base 6791c0c)

Verdict: changes requested

### Findings

1. [must-fix] `src/azure_mcp/tools/_common.py:41-59` (`run()`) — the tech design's own
   "Non-functional" section (`docs/tickets/PRD-21257.md` "Security" bullet) commits to:
   "log `tenant_id` (not secret) + `subscription_id` + tool name + outcome for
   traceability." The implementation does not do this: the only `log.*` call in the whole
   repo is `log.exception("unexpected error in tool handler")` on the unhandled-exception
   path (`_common.py:57`). Every successful call and every structured error outcome
   (`unauthorized`, `not_found`, `invalid_argument`, `rate_limited`, `upstream_error`) is
   never logged — there is no way to trace which tenant made a given failing call once this
   is deployed. This is a committed tech-design behavior that was silently dropped: the
   Self-test section does not mention it as a known gap or deviation anywhere. Fix: add one
   structured log line in `run()` recording at least tool name, `tenant_id` (never the
   client secret), and outcome (`ok` / the error `code`), for both the success and
   `AzureApiError`/`ToolInputError` branches, not just the catch-all `except Exception`.

### Suggestions

1. `src/azure_mcp/client.py:35-42` (`_retry_after`) — the backoff caps `Retry-After` at
   `MAX_BACKOFF = 20.0`s. The design doc says retries should respect `Retry-After` "up to
   the single-call time budget (<120s)" (AC10) — if Azure ever sends a `Retry-After` above
   20s, this waits less than Azure asked for and may hit `429` again sooner than necessary.
   Not a correctness bug (the call still eventually resolves to a structured `rate_limited`
   error within budget, and no AC/test asserts the exact wait value), but worth documenting
   the 20s cap as a deliberate choice next time this file changes, since AC10's wording
   reads as "respect it fully."
2. `src/azure_mcp/tools/advisor.py:54-64` and `resource_health.py:48-57` fetch the full
   ARM result set (no `$top`) and only slice to `limit` client-side via `page()`, unlike
   `resources.py:68` which passes `$top` to ARM itself. Both are correct per the AC/tests,
   but for a subscription with many Advisor recommendations or health events this pulls
   more data from Azure than the page size needs — a token-economy nit (SOP token-economy
   guidance), not a defect.

### Verified this round (not findings — recorded so the next round doesn't re-check)

- `uv run pytest -q` → 30 passed (matches the Self-test claim).
- `uvx ruff check .` → all checks passed (matches the Self-test claim; `ruff` itself is not
  on PATH in the review sandbox so it was run via `uvx`, same tool/version resolution).
- `sudo docker build --platform linux/amd64 -t azure-mcp:review .` → builds successfully.
  This resolves the Self-test section's flagged gap ("Docker build ... could not be run");
  only cosmetic `UndefinedVar` build warnings for the unset `$VERSION`/`$BUILD_DATE`/
  `$COMMIT_SHA` build args (expected — those are meant to be passed by the publish
  pipeline, not baked into the repo).
- Ran the built image: `GET /health` → `200 {"status":"ok"}`; `POST /mcp` with no
  credential headers → `401` (AC8), confirmed against the real container, not just the
  design doc's local-process verification.
- `README.md` lines 11-81 (the MSPbots Connector block) are byte-identical to
  `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md`
  (`diff` clean), positioned before the Header credentials table, per SOP §0.5.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → no output
  (no Chinese anywhere in the repo).
- No plaintext secrets found (`.env.example` is placeholder-only; manual grep for
  high-entropy credential-shaped literals found nothing); `gitleaks` itself is not
  installed in this environment, so the SOP's "gitleaks detect (if available)" step was
  skipped, not run-and-passed.
- `origin/main` is still at `6791c0c` (unchanged since the dev leg synced) — no re-sync
  needed before merge.
- Spot-checked tool code against the Data & API contract table (`subscriptions.py`,
  `resources.py`, `advisor.py`, `resource_health.py`, `monitor.py`) and the structured
  error mapping (`errors.py::status_to_code`): API paths, api-versions, and error-code
  mapping all match the design doc. `tests/test_isolation.py` genuinely exercises
  concurrent `ContextVar` isolation through the real middleware → client path (not a
  trivial/fake test).
- Credentials: read only from the three required headers in `auth.py`, bound to a
  `contextvars.ContextVar`, reset in `finally`; never cached, never logged, no
  environment-variable fallback — matches SOP §3's isolation requirement.

### Fixes (round 1), commit 56e45bf

1. `src/azure_mcp/tools/_common.py` `run()` — changed signature to
   `run(tool_name, settings, handler, *, subscription_id=None)` and added one
   `log.info`/`log.exception` call per outcome: success (`outcome=ok`),
   `AzureApiError` (`outcome=<exc.code>`), `ToolInputError`
   (`outcome=invalid_argument`), and the existing catch-all
   (`outcome=upstream_error`, now also carrying `tool`/`tenant_id`). Every
   call site in `subscriptions.py`, `resources.py`, `advisor.py`,
   `resource_health.py` and `monitor.py` (7 tools) updated to pass its tool
   name; the 6 tools that take `subscription_id` also pass it through so the
   log line matches the design doc's full "`tenant_id` + `subscription_id` +
   tool name + outcome" commitment, not just the must-fix's minimum ask.
   `azure_list_subscriptions` (no subscription scope) and the two
   `monitor.py` tools (scoped by `resource_id`, not `subscription_id`) log
   `subscription_id=None` — there is no subscription argument available at
   that call site to pass.
   - Re-ran `uv run pytest -q` on the fix: 30 passed (no new test added —
     no test harness in this repo currently asserts on `caplog`; verified
     by reading log output directly instead, next bullet).
   - Verified live against the real container (`python -m azure_mcp`,
     `GET /health` -> 200; `tools/list` -> 7 tools) and the real Azure AD
     endpoint: `tools/call azure_list_subscriptions` with placeholder
     tenant/client credentials produced server stderr line
     `INFO azure_mcp tool=azure_list_subscriptions
     tenant_id=00000000-0000-0000-0000-000000000001 subscription_id=None
     outcome=unauthorized` and the response body's `AADSTS90002` error was
     unaffected (same shape as the design doc's error mapping). Grepped the
     full server log for the placeholder client secret value: 0 matches.
   - Also exercised the success, `AzureApiError`, `ToolInputError` and
     unhandled-exception branches directly via a scratch script
     (`~/.claude/skills/mb-ticket-pipeline/scratch/PRD-21257/verify_logging.py`,
     not committed to the repo) with fake credentials bound to the same
     `ContextVar` the middleware uses: all four logged the expected
     `tool=... tenant_id=... subscription_id=... outcome=...` line, never
     the secret.
   - `uvx ruff check .` -> all checks passed.
   - `git diff --stat cabc7e0..56e45bf`: 6 files changed (`_common.py` +
     the 5 tool modules that call `run()`), `README.md` untouched, so the
     round-1 "Verified this round" README/Chinese-text findings still hold
     without re-checking.

## Round 2 · 2026-11-03 · reviewed dev/PRD-21257 @ cd17960 (base 6791c0c)

Verdict: approved

### Findings

None. Checked the single round-1 must-fix against the fix commit (56e45bf) and the
docs-only commit that records it (cd17960); no new must-fix found in either.

### Round 1 must-fix check

1. `src/azure_mcp/tools/_common.py:41-59` (`run()`) — **resolved**. `run()` now takes
   `tool_name` and an optional `subscription_id`, and logs one `log.info`/`log.exception`
   line per outcome branch: success (`outcome=ok`), `AzureApiError` (`outcome=<exc.code>`),
   `ToolInputError` (`outcome=invalid_argument`), and the pre-existing catch-all
   (`outcome=upstream_error`). All 7 call sites (`subscriptions.py` x2, `resources.py`,
   `advisor.py`, `resource_health.py`, `monitor.py` x2) were updated to pass their tool
   name; the 6 that carry a `subscription_id` argument pass it through, matching the
   design doc's full "`tenant_id` + `subscription_id` + tool name + outcome" commitment,
   not just the minimum the must-fix asked for. Never logs `tenant_secret`/client secret —
   confirmed by reading `_common.py` end to end, not just the diff. The one branch that
   does not log (`creds is None` / `not_configured`) is pre-auth: there is no `tenant_id`
   to attribute the call to yet, and the design doc's traceability requirement is about
   attributing calls to a tenant, so this is not a gap.

### Verified this round (independently re-run, not taken from the dev leg's claim)

- `uv run pytest -q` → 30 passed (same count as round 1 and as the dev leg's claim;
  re-run on `cd17960`, not copied from the `[DEV]` stub).
- `uvx ruff check .` → all checks passed.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` → no output.
- `git diff 56e45bf...cd17960 --stat` → only `docs/tickets/PRD-21257-review.md` changed
  (42 insertions, the round-1 Fixes section); no code changed since the commit the dev
  leg's own evidence was gathered against, so round 1's "Verified this round" findings
  (README connector section, Docker build, `/health`/`tools/list`/401 smoke, credential
  isolation, Data & API contract spot-check) still hold without re-checking.

### Suggestions carried over from round 1 (not re-raised, still just suggestions)

1. `src/azure_mcp/client.py:35-42` — `Retry-After` cap at 20s vs. AC10's "<120s" wording.
2. `advisor.py:54-64` / `resource_health.py:48-57` — no `$top` passed to ARM, client-side
   slice only.

Neither touched by the round-1 fix; still non-blocking per the same reasoning as round 1.
