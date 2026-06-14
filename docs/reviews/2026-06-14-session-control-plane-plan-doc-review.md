# Doc Review — Session Control Plane plan (v1 spine)

**Target:** [docs/plans/2026-06-14-session-control-plane-plan.md](../plans/2026-06-14-session-control-plane-plan.md)
**Reviewed revision:** working tree (uncommitted)
**Reviewer pass:** readiness-skeptic (plan classification; no idea/issue/spec rubric phase applies)
**Blocked status:** **UNBLOCKED** — 1 P1 + 5 P2 + 1 P3 found, **all fixed in place** this session (operator: "fixing everything it finds").
**Linked:** [requirements](../brainstorms/2026-06-14-autonomous-session-control-plane-requirements.md) ·
[DECISIONS#phase-sequence-v1-spine](../engineering-journal/DECISIONS.md#phase-sequence-v1-spine)

## Readiness summary

The v1 plan is well-structured (clean U1→U8 DAG, per-unit fakeredis test scenarios, KTDs, R-ID mapping)
and ready to drive `/work`. The readiness pass found one real P1 in the Hermes-integration lifecycle and
several surface/spec gaps a literal `/work` agent would have hit — all evidence-backed and fixed in place.

## Findings — all resolved

| id | pri | finding | fix applied |
|----|----|---------|-------------|
| P1-1 | P1 | **Outbound consumer lifecycle contradiction.** U6 said "started in `register`", but the gateway/adapter is only reachable from a `pre_gateway_dispatch` event ([LEARNINGS#outbound-text-via-discord-py]) — so a consumer started at load time cannot send. | U5 now captures `gateway` on first call; U6 is a **per-target** consumer that starts lazily once a target is set **and** the gateway is captured, stops on disconnect; U7 "wires but does not prematurely start" it. |
| P2-1 | P2 | **DM send path wrong.** `client.get_channel(chat_id)` returns `None` for DMs, so the literal U6 instruction would break DM replies — but R2 requires DM/channel/thread. | U6 now specifies **surface-aware send** (guild channel via `get_channel`; DM via the user/DM channel; thread via the thread channel), with separate DM/channel/thread test cases. |
| P2-2 | P2 | **Inbound field derivation unspecified.** U5 said "build an `Inbound`" without how to derive `source`/`chat_id`/`endpoint` per surface. | U5 now derives `source` from `event.message_type`, `chat_id` from the surface id, `endpoint` from config. |
| P2-3 | P2 | **Consumer scope open.** Per-target vs pooled outbound consumer was undefined. | Decided: **per-target**, lifecycle tied to target set/clear (single-operator, KTD2). |
| P2-4 | P2 | **Matcher/endpoint config shape unpinned.** U4/U7 said "from plugin config" without a source/shape. | Pinned to `plugin.yaml` (host_vars shape: `connect_patterns`/`list_patterns`/`disconnect_patterns`/`mode_phrases`) with built-in defaults; env overrides. |
| P2-5 | P2 | **No phase-level acceptance gate.** Unit tests mock Hermes/Discord, but nothing defined when v1 is "done" end-to-end. | Added an **Acceptance (v1 phase gate)** section: real-Mimir connect/route/reply on DM+channel+thread, disconnect no-regression, `/cc list` + heartbeat drop, CI green. |
| P3-1 | P3 | **No routing-decision logging at v1**, though the strategy's delivery-fidelity / fast-path-capture metrics start mattering at v1. | U5 now logs every routing decision (matched/routed/passed-through) — the seed of the Phase-B audit spine. |

## Residual risk from limited evidence

The Hermes hook/adapter contract (signature, `adapter._client` reach, surface-specific send) is verified
against `asgard_voice_arbiter` and discord.py semantics, **not** against the live `mimir-engineer`
profile. The plan handles this correctly by mocking the Hermes surface at the unit level and gating v1
on a real-Mimir acceptance step (the new Acceptance section) — but the exact per-surface discord.py calls
remain to be confirmed at implementation, which is the right place for it.
