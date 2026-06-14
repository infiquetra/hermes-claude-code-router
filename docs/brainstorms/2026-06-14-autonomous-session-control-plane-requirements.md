---
date: 2026-06-14
topic: autonomous-session-control-plane
maturity: requirements-ready
source: docs/ideation/2026-06-14-autonomy-safety-ideation.md (survivors #1–#7 + revived R2)
---

# Autonomous Session Control Plane — Requirements

## Summary

The complete program for `hermes-claude-code-router`: the operator↔session control plane that lets a
Hermes operator agent (Mimir) drive a fleet of live Claude Code sessions over a durable Redis bus —
both **human-proxied** (a person talks to the agent, which relays/switches/orchestrates) and
**autonomously** (the agent coordinates sessions toward a goal handed to it once, no human in the loop).
This doc captures the whole phased program — the settled human-relay spine plus the autonomy & safety
program — with success criteria per capability; the v1 line and phase sequence are deferred to `/plan`.

## Problem Frame

A running Claude Code session has no durable surface to operate it remotely and conversationally, and
none for an agent to drive it on its own behalf. Today the operator reaches sessions one at a time at a
keyboard; there is no way to multiplex them through a conversational agent, and no control surface an
autonomous agent could use to run them.

The hard part is not the relay — it is that autonomy and human-relay must share **one** substrate
without forking into two products, and that the moment an agent self-approves privileged actions in
real repositories, safety stops being a feature and becomes the foundation. The operator agent and the
worker may be the same underlying model, so "the agent checks its own work" is no real safeguard;
independence has to be structural, not cognitive.

## Key Decisions

**Reversibility is the safety axis, not raw "destructive".** Self-approval gates on whether an action
can be undone on check, not on a danger-keyword match. Reversible actions (including commits/edits that
can be reverted) may self-approve; irreversible actions (force-push to main, `rm -rf` of untracked
state, schema drops) always escalate. Anything not *confidently* classified as reversible defaults to
escalate.

**The gate is deterministic connector code, never a second LLM.** Because the operator and worker can
share weights, a second model pass is not an independent opinion. The connector recomputes an action's
risk classification itself rather than trusting the worker's self-reported flag, and decides via code,
not judgment.

**Self-approval is one more verdict source, not a parallel product.** Autonomous verdicts travel the
existing permission-verdict path (same timeout, audit, scoping) as a distinct source; authority is
granted up front as a scoped, expiring envelope at session spawn, and only out-of-envelope or
irreversible actions escalate to the settled human-relay path.

**Shadow before live.** Self-approval runs in observe-and-log mode against real human verdicts, and is
only enabled for real once its measured false-approval divergence is acceptable.

**Decomposition stays in the agent.** The connector never holds or reasons about the goal; it provides
one fan-out/fan-in correlation primitive and stays dumb durable plumbing. (The opposite bet — a
reconcile loop inside the connector — is recorded as a revisit-if-fragile alternative, not the plan.)

**Isolation is encouraged, not enforced.** The connector does not mandate scratch-branch/worktree
isolation; the reversibility classifier and the irreversible-always-escalate wall carry the weight
instead. The resulting "commit/push-to-main misclassified as reversible" gap is an explicitly accepted
risk (see Dependencies / Assumptions).

## Actors

- A1. **Operator agent (Mimir)** — the primary customer; consumes the connector's tools and verdict
  path to discover, route, switch, and orchestrate sessions, whether relaying a human or acting
  autonomously.
- A2. **Claude Code worker sessions** — the fleet being driven; register presence, receive inbound
  text, emit replies, task-state, and permission requests.
- A3. **The human** — a customer of the agent, not of the connector; out of this doc's surface except
  as an escalation target.
- A4. **The connector** — the control plane itself: routing state, the deterministic safety gate, the
  audit spine, the kill switch, and the agent-facing tools.

## Requirements

**Human-relay control plane (the settled spine).**

- R1. The connector maintains a routing target per operator conversation; when set, operator text is
  forwarded to the targeted session instead of the agent's own LLM, and when unset the agent's normal
  behavior is unchanged.
- R2. The connector matches operator phrases (slash + regex, configurable per endpoint) to manage
  routing state: connect, disconnect, list, switch, and routing on/off.
- R3. With a target set, inbound operator text is forwarded to the session and the session's replies
  are relayed back to the originating surface (DM, channel, thread).
- R4. The connector reads the session presence registry and heartbeat to surface live sessions on
  demand, excluding stale ones.

**Session observability.**

- R5. The connector can determine each session's task-state — at least idle, working, blocked,
  completed, errored, and waiting-on-approval — via a hybrid of signals it can derive and signals the
  worker must emit. Verified mechanism (Claude Code surfaces no native turn-complete or error
  notification to a channel plugin, and that surface is not ours to change): blocked-on-permission comes
  from the permission stream; working/idle-after-turn is derived from inbound-dispatched vs
  outbound-reply-arrived; completed-goal, blocked-mid-task, and errored require **worker-cooperative
  markers** the session emits via the reply tool (coached), since they are not otherwise observable.
- R6. Task-state is readable as current truth at any time, not only as a transition event — it survives
  connector restarts and dropped at-most-once delivery.
- R7. The connector derives waiting-on-approval itself from the permission streams it already owns,
  with no protocol change required for that state specifically.
- R8. The connector can distinguish "alive but not progressing" from "actively working", rather than
  inferring completion from reply silence.

**Self-approval & safety model.**

- R9. Self-approval verdicts are produced by deterministic connector logic, never by a second LLM call.
- R10. The connector classifies each requested action's reversibility independently, recomputing it
  rather than trusting the worker's self-reported flag.
- R11. Reversible actions within a session's granted envelope self-approve; irreversible actions always
  escalate; any action not confidently classified as reversible defaults to escalate.
- R11a. Confidentiality- and egress-class actions are a **separate escalation class, gated regardless of
  reversibility**: reads of secret-bearing paths, network egress (e.g. `curl`, pushing to an arbitrary
  remote), and external-effect actions (publish, send, external API calls with side effects). These
  change nothing locally — so reversibility would wrongly self-approve them — yet are
  confidentiality/exfiltration risks, so they never self-approve.
- R12. Self-approval is expressed as a distinct verdict source on the existing permission-verdict path,
  reusing its timeout, audit, and scoping — not a parallel approval mechanism.
- R13. A session's autonomous authority is granted as a scoped, expiring envelope at spawn time
  (allowed action classes, path scope, forbidden operations, ceilings); out-of-envelope requests
  escalate. A session with no granted envelope has zero autonomous authority — every request escalates
  (the safe default).
- R14. Reversible-but-committed actions carry a pre-declared compensation (a recorded inverse) so
  "undo on check" is concrete rather than improvised after the fact.

**Failure, recovery & escalation.**

- R15. A non-bypassable kill switch at the connector's forwarding/verdict chokepoint halts all
  forwarding and auto-denies pending permission requests; it is throwable by the operator or tripped by
  breached safety counters (e.g. destructive-ops/min, writes/goal, branches-touched). The human retains
  kill-switch access at all times, including out-of-band during a fully autonomous run. The switch bounds
  *future* actions: it cannot retract an action already executing inside a worker, so blast-radius
  bounding still relies on the reversibility gate and counters upstream of dispatch.
- R16. A fast safety-stop takes precedence over any in-flight goal or plan step (precedence is
  pre-decided, not negotiated at runtime).
- R17. When an autonomous session cannot self-clear an action and no human is available, it reaches a
  Minimal Risk Condition — checkpoint work, go idle, mark blocked — rather than blocking forever or
  proceeding unsafely.
- R18. On worker death or crash, the connector applies a configurable supervision strategy
  (restart-and-resume the goal, escalate, or terminate), generalizing the existing target-lost reset.
  The **safe default is escalate-and-hold** (mark the goal blocked, do not auto-restart); restart-resume
  is opt-in per session, never the default.
- R19. Escalation is silence/exception-driven: a blocked or stalled session raises attention while
  healthy sessions stay quiet — no polling of the whole fleet by default.

**Orchestration & autonomy rungs.**

- R20. Goal decomposition lives in the operator agent; the connector neither holds nor reasons about
  the goal.
- R21. The connector provides a fan-out/fan-in correlation primitive: operator-stamped goal/subtask
  identifiers (unique per goal, to prevent fan-in cross-contamination) are carried through to the
  matching replies, and replies for a goal can be collected across N sessions.
- R22. **Fire-and-check** — an operator dispatches a task and learns, via task-state plus correlation,
  when it completed, blocked, or errored, without watching it.
- R23. **Supervise-and-approve** — the connector answers a session's permission requests via the
  deterministic gate so an in-envelope reversible action does not block on a human.
- R24. **Coordinate-toward-a-goal** — the agent drives several sessions toward one handed-off goal, the
  connector reconciling state and surfacing exceptions, until the goal lands or escalates.

**Agent-operability surface.**

- R25. The connector exposes machine-legible LLM tools for the operator agent (not human-formatted
  output): a fleet status read giving per-session state for check, supervise, and coordinate.
- R26. The connector exposes a self-authority read so an agent can query its own current envelope and
  kill-state before acting.
- R27. The same operability tools serve a human-proxied operator and an autonomous one identically.

**Protocol, audit & rollout.**

- R28. The task-state signal is added as an additive, backward-compatible protocol change carrying both
  worker-emitted markers and router-derived state (not a hook into a Claude Code turn-lifecycle event,
  which does not exist), keeping the shared protocol models byte-identical across both repos via
  synchronized PRs.
- R29. The audit log is the single append-only spine feeding metrics, observability, and the policy
  corpus; every routing decision and permission verdict (human, autonomous, and shadow) appends a
  structured line carrying an attributable rule/reason. The log must be durable and append-only
  (survives restarts, not truncated on rotation without retention), since it is load-bearing for both
  the false-approval metric and post-incident forensics.
- R30. Shadow mode: the autonomous verdict is computed and logged against the human's real verdict
  without being enforced, until a false-approval threshold is met; only then is live self-approval
  enabled.

## Key Flows

- F1. **Human-relay text round-trip.** **Trigger:** operator connects to a session and sends text.
  Operator phrase sets the routing target (R1, R2); text forwards to the session (R3); the session's
  reply relays back to the originating surface (R3). **Covers R1–R4.**
- F2. **Fire-and-check.** **Trigger:** operator (or the agent itself) dispatches a task to a session.
  The agent stamps a correlation id (R21), the session works, task-state moves working → completed (or
  blocked/errored) (R5–R8), the agent reads the correlated result and reports. **Covers R5–R8, R21,
  R22.**
- F3. **In-envelope reversible self-approval.** **Trigger:** a supervised session requests a reversible
  action inside its envelope. The connector recomputes reversibility (R10), confirms it is in-envelope
  and reversible (R11, R13), and emits an autonomous-source allow on the existing verdict path with a
  pre-declared compensation recorded (R12, R14). **Covers R9–R14, R23.**
- F4. **Irreversible-action escalation → MRC.** **Trigger:** a session requests an irreversible action,
  or one the connector cannot confidently classify. The connector escalates to the human-relay path
  (R11); if no human is available, the session reaches a Minimal Risk Condition (R17). **Covers R11,
  R17, R19.**
- F5. **Coordinate-toward-a-goal.** **Trigger:** a goal is handed to the agent once. The agent
  decomposes it (R20), fans subtasks out across sessions with correlation ids (R21), reconciles
  task-state and replies (R5–R8), self-approves in-envelope reversible steps (F3), escalates the rest
  (F4), and drives to completion or escalation (R24). **Covers R20–R24.**
- F6. **Kill switch / counter breach.** **Trigger:** the operator throws the kill switch, or a safety
  counter is breached. The connector halts forwarding, auto-denies pending permission requests, and the
  fast-stop preempts any in-flight step (R15, R16). **Covers R15, R16.**

## Acceptance Examples

- AE1. **In-envelope reversible action self-approves.** Given a session granted an envelope permitting
  edits under its working tree, when it requests an edit the connector classifies as reversible, then
  the connector emits an autonomous allow on the verdict path and records the inverse. **Covers R11,
  R12, R14.**
- AE2. **Irreversible action escalates even when in-envelope.** Given the same session, when it requests
  a force-push or a delete of untracked state, then the connector escalates regardless of envelope —
  irreversible never self-approves. **Covers R11.**
- AE3. **Unclassifiable action defaults to escalate.** Given an action the connector cannot confidently
  classify as reversible, then it escalates rather than self-approving. **Covers R11.**
- AE4. **No human + irreversible → Minimal Risk Condition.** Given an escalation with no human
  available, then the session checkpoints, goes idle, and is marked blocked rather than proceeding or
  hanging indefinitely. **Covers R17.**
- AE5. **Counter breach halts the fleet.** Given destructive-ops/min exceeds its ceiling, then the kill
  switch trips: forwarding stops, pending permission requests are denied, and the stop preempts any
  in-flight step. **Covers R15, R16.**
- AE6. **Shadow divergence is logged, not enforced.** Given shadow mode is active, when the autonomous
  verdict differs from the human's, then both are logged with attribution and only the human's verdict
  is enforced. **Covers R29, R30.**

## Scope Boundaries

**Deferred for later (in the program, not necessarily v1 — `/plan` sets the line):**

- The three autonomy rungs land incrementally; observability and the human-relay spine precede live
  self-approval.
- Enforced isolation (scratch-branch/worktree mandate) — revisitable if the accepted reversibility risk
  proves real.
- A reconcile loop inside the connector (the R4 alternative to agent-side decomposition) — revisit only
  if agent-side orchestration proves too fragile to lost events.

**Outside this product's identity:**

- Operator-interface I/O — voice capture, TTS/playback, Discord surface mechanics, typed-vs-spoken —
  is upstream and owned by the Hermes agent; the connector only ever speaks text.
- Multi-user concurrent routing (single-operator by design).
- Cross-WAN access and alternate surface bridges (Telegram/iMessage/SMS).
- Session-*mode* awareness or toggling (plan/accept-edits is unknowable to the channel protocol;
  task-state is the in-scope substitute, and is a different thing).
- Implementation specifics — schemas, exact payload fields, stream names, file layout, library choices —
  belong to `/plan`.

## Success Criteria

Quality signals beyond the requirements; all are instrumented in the connector decision-log /
`audit.jsonl` and none is measurable until the connector is built.

- **Delivery fidelity** — operator messages reach the intended live session and a reply returns;
  misroutes, leaks to the agent's LLM when a target was set, and drops to dead/phantom sessions count as
  failures.
- **Round-trip latency** — operator text → session → reply.
- **Fast-path capture rate** — share of routing intent resolved by slash/regex without LLM fallback.
- **Autonomous goal-completion rate** — handed-off goals the agent lands without human intervention.
- **Permission false-approval rate** — autonomous approvals that should have been denied; the metric
  shadow mode produces against human ground truth.
- **Shadow divergence rate** — the gate that must be acceptable before live self-approval is enabled
  (threshold deferred to `/plan`).

## Dependencies / Assumptions

- **Cross-repo prerequisite (needs its own issue/plan).** Task-state (R5, R28) and worker-cooperative
  markers require changes on the CC-side `redis-channel` plugin in `infiquetra/infiquetra-claude-plugins`
  — channel coaching so the worker emits markers, plus the marker-carrying protocol field — which this
  doc cannot drive. Track it as a separate `infiquetra-claude-plugins` work item; the shared protocol
  models stay byte-identical. The operator owns both repos, so this is coordinated, not external.
- **Operator-agent orchestration capability (load-bearing assumption).** Coordinate-toward-goal (R24)
  assumes the operator agent's LLM can reliably decompose a goal and reconcile fan-in. If it cannot, the
  top rung fails regardless of the connector. Validate with an early feasibility check before building
  R24's surface.
- **Additive evolution is sanctioned.** The wire contract already ignores unknown fields and permits
  optional additions, so task-state, new verdict sources, correlation ids, and audit attribution are
  backward-compatible additions, not breaking changes.
- **Spawn primitive.** Programmatic session launch must use a tmux-detached-foreground path, because
  background-dispatched sessions silently drop channel notifications — verified CC-side constraint.
- **Accepted risk — isolation not enforced.** Without mandated isolation, a commit or push to `main`
  can be misclassified as reversible. Mitigated, not eliminated, by the conservative classifier
  (default-escalate on uncertainty) and the irreversible-always-escalate wall; recorded here as a known
  tradeoff the operator chose.
- **Single operator.** Routing state stays per-conversation and need not be shared across processes.
- **STT confidence is irrelevant here.** Deterministic self-approval consumes structured action fields,
  not a transcribed yes/no, so the unsurfaced-STT-confidence limitation does not constrain this program.

## Outstanding Questions

_Resolved in doc-review (2026-06-14): the confidentiality/exfiltration gap is now R11a (separate
escalation class); task-state feasibility was verified — Claude Code exposes no native turn-complete/error
signal, so R5/R28 now specify a derived-states + worker-cooperative-markers mechanism. Nothing remains
that blocks planning._

**Deferred to planning** (answered during `/plan` or codebase exploration):

- The v1 line and the phase sequence across the whole program.
- The shadow-mode enable threshold (what false-approval/divergence rate permits live self-approval).
- The exact reversibility classification of ambiguous Bash, and the positive-allowlist vocabulary.
- The capability/ROE envelope vocabulary (action classes, scope grammar, ceilings, expiry).
- Whether and when to enforce isolation, or to move a reconcile loop into the connector (the recorded
  alternatives).

## Sources / Research

- [STRATEGY.md](../../STRATEGY.md) — target problem, dual-operator approach, agent-as-customer, metrics,
  non-goals.
- [DECISIONS#dual-operator-autonomy-co-equal](../engineering-journal/DECISIONS.md#dual-operator-autonomy-co-equal)
  — the direction expansion this program implements.
- [docs/ideation/2026-06-14-autonomy-safety-ideation.md](../ideation/2026-06-14-autonomy-safety-ideation.md)
  — survivors #1–#7 and the revived reversibility model (R2) this doc builds on.
- [narratives/2026-05-26-router-build-plan.md](../engineering-journal/narratives/2026-05-26-router-build-plan.md)
  — the human-relay spine (needs reconciliation: voice is now upstream, permission now foundational).
- CC-side contract — `infiquetra/infiquetra-claude-plugins` `plugins/redis-channel/` PROTOCOL.md /
  protocol.py / STATE_MACHINE.md (registry, heartbeat, inbound/outbound, permission streams, the
  task-state gap, `--bg` constraint).
- [LEARNINGS.md](../engineering-journal/LEARNINGS.md) — Hermes `register(ctx)` surface,
  `pre_gateway_dispatch` contract, out-of-band send pattern.
- External prior art (autonomy & safety): SAE J3016 ODD + Minimal Risk Condition; OPA policy-as-code;
  object-capability security; k8s reconciliation + liveness/readiness; Erlang/OTP supervision; saga
  compensating transactions; SEC 15c3-5 kill switch (Knight Capital); immune two-signal costimulation.
