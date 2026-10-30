# Archive — `hermes-claude-code-router`

> **Shipped + rejected + superseded items.** When a QUEUED item lands or gets explicitly rejected, its entry moves here. When a LEARNING / DECISION is invalidated, the pre-correction version comes here (annotated SUPERSEDED) so the historical chain stays intact.
>
> Format:
>
> ```markdown
> ## YYYY-MM-DD
>
> ### Short title — SHIPPED (commit-hash) / REJECTED / SUPERSEDED  {#slug}
>
> **Outcome.** Shipped / rejected / superseded.
> **Refs.** Pointer to the original QUEUED / LEARNINGS / DECISIONS entry it came from.
> **Notes.** (if rejected/superseded) Reason.
> ```

---

## 2026-10-29

### Same-major setup-uv cache policy — SUPERSEDED  {#setup-uv-v3-cache-policy-superseded}

**Outcome.** Superseded after hosted restore/save failure and authenticated
provider readback found no cache entries. Source review and a success log did
not establish cache service compatibility. The v3 client uses the retired API;
use the controlled v5 repair in [LEARNINGS](LEARNINGS.md#setup-uv-v3-cache-policy).

**Evidence.** Frozen candidate `b20da0fcf12002895323f20ebe3e1acd2f5f31ea`;
runs `40988491433` and `40988491434`. The following is the exact pre-correction
learning, retained for history:

### setup-uv v3 needs explicit caching and interpreter identity  {#setup-uv-v3-cache-policy}

**Context.** The validation jobs used setup-uv v3 with its cache disabled by
default, and the unit job installed dependencies without `--locked`.

**Evidence.** `.github/workflows/ci.yml`; `.github/workflows/redis-compatibility.yml`;
upstream setup-uv `action.yml`, `src/utils/inputs.ts`, `src/setup-uv.ts`,
`src/cache/restore-cache.ts`, and `src/save-cache.ts`
at `caf0cab7a618c569241d31dcd442f54681755d39`. Successful hosted runs
`40979870881` (unit, 12 seconds) and `40979870738` (compatibility, 19 seconds)
are individual timing samples, supporting a generous five-minute job deadline.

**Mechanism.** v3 keys its download archive by platform, architecture, uv
version, dependency-file hash and optional suffix. It restores before our Python
installation, so `python-3.12` identifies the declared interpreter policy; it
does not claim an observed interpreter patch version. The input reader resolves
`cache-local-path`; setup exports it as `UV_CACHE_DIR` before restoring, so later
commands use the same directory without a duplicate job environment. Cache
misses and caught restore transport errors leave the validation commands unconditional. Save
errors are reported by the post action. Default `uv cache prune --ci` remains
enabled and can remove downloaded wheels, so enabling caching alone does not
establish a speedup.

**Fix.** Set `cache-local-path` to `${{ runner.temp }}/uv-cache` on the hosted
Ubuntu jobs, outside the checkout, environments and tool installs.
Key by `uv.lock` and Python policy; pin the existing action majors and use
`uv sync --locked` in both jobs. Scope cancellation to the workflow and PR, with unique run IDs for
non-PR work so main, release and manual validations remain independent.

**Validation.** Unchanged 126-test collection and passing unit suite, Ruff,
mypy and actionlint. Local execution of the official input reader, setup and
cache functions verifies the export before restore, miss/hit/restore-error
paths and an inherited cache directory override, with mocked transport. Local expression checks
cover cancellation policy. Hosted cache provider/consumer, transport, race and
real-service results remain separate operational checks; no time or financial
savings are claimed.

**Generalizable rule.** Verify the selected action major's key, archive and
failure behavior; a cache must leave authoritative validation unconditional.

---
