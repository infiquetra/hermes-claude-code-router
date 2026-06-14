---
date: 2026-06-14
topic: autonomy-safety
focus: autonomy & safety design of the connector (Mimir-drives-sessions, no human in the loop)
scope: broad
repo: hermes-claude-code-router
maturity: idea-ready
---

# Ideation: Autonomy & Safety for the Session Control Plane

> Run `ef8d34bf`. 49 candidates / 5 frames → 7 survivors. Feeds `/brainstorm` of the whole project
> (human-relay + autonomy) into a unified requirements doc. Survivors marked `Explored` on handoff.

## Grounding Context

**Repo:** `hermes-claude-code-router` is the operator↔session **control plane** (a Hermes plugin)
between an operator agent (Mimir) and live Claude Code worker sessions over a durable Redis bus.
Per [`STRATEGY.md`](../../STRATEGY.md), autonomy is a **co-equal destination** with human-relay
(success-definer: "Mimir handed a goal once, coordinates across sessions to land it, no human in the
loop"); the agent is the customer; voice/Discord is upstream; metrics live in a router decision-log /
`audit.jsonl`. Per [`DECISIONS#dual-operator-autonomy-co-equal`](../engineering-journal/DECISIONS.md#dual-operator-autonomy-co-equal),
permission/safety moved from deferred to **foundational**. Human-relay control plane is already
settled (matchers → routing-target state → XADD inbound / XREADGROUP outbound → reply).

**Named repos:** `infiquetra/infiquetra-claude-plugins` (the CC-side `redis-channel` plugin) — read
for what the protocol can expose. Findings: the protocol exposes registry metadata
(session_name/host/cwd/git_branch/pid/started_at/`capabilities[]`), heartbeat (liveness only),
inbound/outbound text, and permission_request/verdict streams; it has **no task-state signal**
(observability gap); `permission_request` already carries `tool_name`+`input_preview`+`destructive`
(safety sufficient for gating); `_Versioned` has `extra="allow"` so additive evolution is sanctioned;
`is_destructive()` is shared + router-recomputable; spawn must use tmux-foreground (`--bg` drops
channel notifications).

**Context-libraries:** None consulted (architecture topic, not an org-convention topic).

## Topic Axes

1. Session observability — how the agent sees worker state (done/blocked/errored/waiting).
2. Goal-decomposition & orchestration boundary — agent vs connector vs split.
3. Per-action safety / self-approval — replacing the human yes/no for one privileged action.
4. Failure, recovery & escalation — kill switch, rollback/compensation, circuit-break, safe-state.
5. Connector orchestration-surface exposure — what the connector exposes for an agent operator.

## Ranked Survivors

### 1. `task_state` observability event

The connector learns idle/working/blocked/completed/errored — today it only knows heartbeat-alive vs
stale.

Add an additive `task_state` event on the existing `cc-sessions:events:<name>` pub/sub, backed by a
durable `SET` state mirror (pub/sub is at-most-once → level-triggered reads beat edge events), plus a
`progress_seq` to catch "alive but deadlocked." The router derives `waiting_on_approval` for free — it
already owns both ends of the permission streams (no cross-repo change for that half).

The journal's "session-mode is invisible, period" was a category error: *mode* is unknowable but
*task-state* is just uninstrumented, and `extra="allow"` sanctions adding it. It's the precondition
for all three autonomy rungs — 6 frames landed here. Downside: the CC-side emission is a synchronized
cross-repo PR.

| field | value |
|-------|-------|
| basis | `direct:` PROTOCOL observability gap + `protocol.py:59` `extra="allow"` |
| confidence | 90 |
| complexity | Med |
| axis | 1 — observability |
| status | Explored |

### 2. Structural independence + the v1 safety floor

The self-approval gate is deterministic router code, not a second LLM — because operator and worker
may be the same model.

Make the gate deterministic; have the router **recompute `is_destructive()`** rather than trust the
worker's self-graded bit; gate on a **positive default-deny allowlist** (a denylist false-negative
auto-executes under self-approval); v1 ODD = auto-approve non-destructive, always escalate destructive.

Operator==worker means cognitive self-review is theater — independence must be structural (immune
two-signal, Airbus PF/PM, IEC-61508 independent SIS converge here). Downside: a strict allowlist
front-loads the "what's safe" enumeration and feels conservative early.

| field | value |
|-------|-------|
| basis | `direct:` `protocol.py:42` `is_destructive()` recomputable · `reasoned:` shared-weights = no second opinion |
| confidence | 88 |
| complexity | Low |
| axis | 3 — self-approval |
| status | Explored |

### 3. Spawn-time capability/ROE envelope + self-approval as a verdict `source`

Approve once at spawn via a scoped envelope; in-envelope actions self-approve, out-of-envelope
escalates.

Mint a scoped, expiring authority envelope into the live-but-unused `capabilities[]` registry field at
spawn; in-envelope actions self-approve via a new `VerdictSource = "policy"` that **reuses the entire
existing permission spine** (timeout, echo-confirm, audit, chat_id scoping); out-of-envelope falls back
to the settled human-relay path.

Collapses per-action gating to one deliberate spawn-time grant and makes autonomy "one more verdict
source," not a forked product (the strategy's hard non-goal). Downside: envelope-too-tight floods
escalations, too-loose is the blast-radius risk — the envelope vocabulary is the real design work.

| field | value |
|-------|-------|
| basis | `direct:` `RegistryEntry.capabilities` + `VerdictSource` literal · `external:` object-capability security |
| confidence | 82 |
| complexity | Med |
| axis | 3 — self-approval |
| status | Explored |

### 4. `audit.jsonl` event-sourced spine + shadow mode

One append-only log feeds metrics + observability + a policy-training corpus; self-approval runs in
shadow before it's ever enforced.

Verdicts carry `policy_rule_id`+reason (OPA-style) so false-approvals are attributable. Shadow mode
computes the would-be autonomous verdict against the human's real verdict, enforces only the human's,
and measures the false-approval rate **before** enabling self-approval.

The safest on-ramp — you earn the right to flip autonomy on by proving low divergence, and it directly
produces the "permission false-approval rate" metric. Downside: shadow delays real autonomy until
enough human verdicts accumulate.

| field | value |
|-------|-------|
| basis | `direct:` STRATEGY audit.jsonl commitment · `external:` ML shadow deployment / OPA Gatekeeper |
| confidence | 86 |
| complexity | Med |
| axis | 3 / cross-cutting |
| status | Explored |

### 5. Non-bypassable kill switch + autonomous failure ladder

A stop that doesn't depend on the rogue worker cooperating, plus a designed safe state for 3am.

A `halted` flag at the router XADD-inbound + verdict-write **chokepoint** (Knight Capital: limits
upstream of execution, non-bypassable), tripped by an operator phrase or breached counters
(destructive-ops/min, writes/goal, branches-touched), fast-stop preempting the slow plan (TCAS
precedence). Ladder: no-human/blocked → Minimal Risk Condition (checkpoint WIP to scratch branch,
idle); crash → configurable supervision strategy generalizing R5 target-lost (restart-resume / escalate
/ terminate); destructive steps carry pre-declared compensations for backward saga replay.

Autonomy you'd run on your own repos needs both a hard stop and a designed fallback. Downside: the
compensation/MRC machinery is the heaviest single build in the set.

| field | value |
|-------|-------|
| basis | `external:` SEC 15c3-5 kill switch / J3016 MRC / OTP supervision · `direct:` STATE_MACHINE R5 target-lost |
| confidence | 85 |
| complexity | Med-High |
| axis | 4 — failure/recovery |
| status | Explored |

### 6. Machine-legible status/authority read-tools

The autonomy surface is two LLM tools the agent calls, not text it parses.

Expose `session_status` (fleet state: branch/cwd/task_phase/waiting/current_goal/last_seen — one schema
for check + supervise + coordinate) and `get_session_authority` (the agent reads its own envelope and
kill-state, so limits are legible before it acts).

The agent is the customer, so the surface must be machine-legible tools — and the same two serve
human-proxied and autonomous Mimir identically. Downside: schema churn as `task_state`/envelope evolve
underneath them.

| field | value |
|-------|-------|
| basis | `direct:` STRATEGY agent-ergonomics + LEARNINGS `register_ctx` tool surface |
| confidence | 80 |
| complexity | Low-Med |
| axis | 5 — exposure |
| status | Explored |

### 7. Decomposition stays in the agent; connector adds a fan-out/fan-in correlation primitive

Resolve the open boundary: Mimir owns the goal graph; the connector stays dumb plumbing plus one
correlation primitive.

LLM goal-decomposition lives in Mimir (volatile reasoning); the connector adds `goal_id`/`subtask_id`
stamped through the free-form `Inbound.metadata` and a "collect replies for goal_id across N sessions"
read.

Keeps the connector a stable wire contract (mission-command radio net, not the commander) and honors
the decoupling the approach rests on. Downside: puts orchestration robustness on Mimir's reasoning —
see R4 for the opposite bet.

| field | value |
|-------|-------|
| basis | `direct:` open `#dual-operator-autonomy-co-equal` ADR + `Inbound.metadata` · `external:` mission command / Auftragstaktik |
| confidence | 80 |
| complexity | Low-Med |
| axis | 2 — boundary |
| status | Explored |

## Did not survive (revivable)

| id | title | summary | reason | status |
|----|-------|---------|--------|--------|
| R1 | Dry-run / plan→apply frozen diff | Approve the diff, apply byte-identical (Terraform) | Cut for economy; strong refinement of #2/#3 for the destructive path — revive when designing it | rejected |
| R2 | Reversibility tiering of `is_destructive` | bool → safe\|reversible\|destructive\|irreversible | Overlap with #2; revive when defining the allowlist/tier vocabulary | rejected |
| R3 | Supervisor-presence dead-man's-switch | Autonomy needs policy-allow AND supervisor-present (reuse heartbeat) | Folds into #2/#5; revive when designing the two-signal rule | rejected |
| R4 | Reconcile-loop *in the connector* | Connector holds goal-as-desired-state, robust to lost events | Opposite bet to #7; pushes goal-state into the connector vs the strategy boundary — revive if agent-side orchestration proves fragile | rejected |

No axis was zeroed — all five carry ≥1 survivor.

## Co-ideation log

| source | entered | idea / seed | outcome |
|--------|---------|-------------|---------|
| user-seed | Phase 0 | tool-class allowlists | absorbed into #2 (frames sharpened to positive default-deny allowlist) |
| user-seed | Phase 0 | policy engine | absorbed into #3/#4 (verdict source + OPA-style attributable rules) |
| user-seed | Phase 0 | dry-run-first | cut → R1 (strong but folded; revivable for the destructive path) |
| user-seed | Phase 0 | bounded blast-radius | absorbed into #3/#5 (envelope + counters) |
| user-seed | Phase 0 | audit-only mode | survived as #4 (frame 4 built it into shadow mode) |
| frame-agent | Phase 2 | task_state event | survived as #1 (6-frame convergence) |
| frame-agent | Phase 2 | deterministic gate / operator==worker | survived as #2 (assumption-break) |
| frame-agent | Phase 2 | spawn-time capability envelope | survived as #3 (inversion + assumption frames) |
| frame-agent | Phase 2 | kill switch + MRC + compensation | survived as #5 (pain + cross-domain) |
| frame-agent | Phase 2 | status/authority read-tools | survived as #6 (leverage) |
| frame-agent | Phase 2 | decomposition-in-agent + correlation | survived as #7 (inversion/assumption) |
| frame-agent | Phase 2 | reconcile-loop in connector | cut → R4 (tensions strategy boundary) |
