# Doc Review — Autonomous Session Control Plane requirements

**Target:** [docs/brainstorms/2026-06-14-autonomous-session-control-plane-requirements.md](../brainstorms/2026-06-14-autonomous-session-control-plane-requirements.md)
**Reviewed revision:** working tree (uncommitted)
**Reviewer pass:** readiness-skeptic (requirements classification; no idea/issue/spec rubric phase applies)
**Blocked status:** **UNBLOCKED** (2026-06-14) — all 8 findings resolved or accepted in the same review
session; see Resolution log below. Ready to drive `/plan`.
**Linked:** [STRATEGY.md](../../STRATEGY.md) · [ideation](../ideation/2026-06-14-autonomy-safety-ideation.md) ·
[DECISIONS#dual-operator-autonomy-co-equal](../engineering-journal/DECISIONS.md#dual-operator-autonomy-co-equal)

## Readiness summary

Well-structured and largely ready — 30 IDed requirements, flows, acceptance examples, and honest
scope boundaries. But two findings sit at the *core* of the autonomy design and must be resolved before
`/plan` commits to the safety model: the chosen safety axis (reversibility) has a confidentiality blind
spot, and the headline observability capability rests on an unverified upstream signal. Most of the
program (human-relay spine, orchestration boundary, agent-operability surface) is plannable as written.

## Applied safe fixes

| fix | location | change |
|-----|----------|--------|
| F1 | R13 | Added the safe default: a session with no granted envelope has zero autonomous authority (every request escalates). Implied by the doc's default-escalate principle. |
| F2 | R15 | Clarified the human retains kill-switch access at all times incl. autonomous runs, and that the switch bounds *future* actions only — it cannot retract an action already executing in a worker. Mechanically accurate correction of an overpromise. |
| F3 | Outstanding Questions | Split out "Resolve before planning" and recorded the two P1 findings there so the doc honestly reflects its blocked posture. |

## Findings by priority

| id | priority | status | finding |
|----|----------|--------|---------|
| P1-1 | P0-adjacent safety | open (flagged in doc) | **Confidentiality/exfiltration not covered by the reversibility axis.** Reading a secret, a network egress (`curl`, push to an arbitrary remote), publishing, or sending changes nothing locally → classifies as "reversible" → self-approves, while being a confidentiality/exfiltration disaster. Reversibility ≠ safety for read-and-leak. Needs an egress/secret-read escalation class orthogonal to reversibility, or an explicit accepted-risk decision. |
| P1-2 | core dependency | open (flagged in doc) | **Task-state emission feasibility unverified.** R5–R8 (the whole observability axis, and the precondition for every autonomy rung) assume the CC-side plugin can detect + emit completed/blocked/errored. The journal only established session *mode* is invisible; nobody verified Claude Code surfaces *task completion/blocked* to a channel plugin. Verify the upstream signal exists before planning builds on it. |
| P2-1 | scope split | open | **Cross-repo work boundary under-scoped.** The task-state protocol change lives in `infiquetra/infiquetra-claude-plugins` (CC side) and cannot be implemented from this doc. Dependencies names the sync requirement but not that the CC-side work needs its own plan/issue — a planner may treat it as in-repo. |
| P2-2 | assumption | open | **"Mimir can orchestrate" is unstated and load-bearing.** Coordinate-toward-goal (R24) depends on the operator agent's LLM reliably decomposing a goal and reconciling fan-in. If it can't, the rung fails regardless of the connector. Surface as an explicit assumption + an early feasibility check. |
| P2-3 | open-choice | open | **R18 supervision strategy has no specified default.** "Configurable (restart/escalate/terminate)" without a safe default leaves a planner to invent one for a safety-critical path. |
| P2-4 | completeness | open | **Audit-log integrity/retention unspecified.** The audit spine (R29) is load-bearing for the false-approval metric *and* safety forensics, but nothing requires it to be durable, append-only-guaranteed, or retained. |
| P3-1 | polish | open | **Correlation-id uniqueness not required (R21).** Id reuse across goals could cross-contaminate fan-in. |
| P3-2 | polish | open | **Success criteria carry no targets.** Acceptable per the strategy "which metric, not what value" convention, but the shadow enable-threshold (R30's gate) is unfalsifiable until `/plan` sets it (already in deferred-to-planning). |

## Resolution log (2026-06-14, same session)

| id | resolution |
|----|------------|
| P1-1 | **Resolved** — added R11a: confidentiality/egress actions are a separate escalation class, gated regardless of reversibility. |
| P1-2 | **Resolved (verified)** — verification confirmed Claude Code exposes no native turn-complete/error notification to a channel plugin. R5 and R28 rewritten to a hybrid: derive working/idle/blocked-on-permission from existing streams; require worker-cooperative markers (emitted via the reply tool) for completed/blocked-mid-task/errored. CC-side marker support recorded as a cross-repo prerequisite. |
| P2-1 | **Resolved** — Dependencies now flags the CC-side work as a separate `infiquetra-claude-plugins` issue/plan this doc cannot drive. |
| P2-2 | **Resolved** — added the operator-agent orchestration-capability assumption + an early feasibility check before R24. |
| P2-3 | **Resolved** — R18 now specifies the safe default: escalate-and-hold; restart-resume is opt-in. |
| P2-4 | **Resolved** — R29 now requires the audit log be durable and append-only. |
| P3-1 | **Resolved** — R21 now requires correlation ids unique per goal. |
| P3-2 | **Accepted by design** — success-criteria targets stay deferred to `/plan` per the strategy "which metric, not what value" convention. |

## Residual risk from limited evidence

The task-state mechanism (P1-2) now leans on worker-cooperative markers — the session must reliably emit its own state via the reply tool. Whether a coached worker emits accurate markers consistently is the new load-bearing unknown in the observability axis, downgraded from "is it even possible" to "how reliable is the marker discipline," and should be validated empirically once the CC-side coaching ships.
