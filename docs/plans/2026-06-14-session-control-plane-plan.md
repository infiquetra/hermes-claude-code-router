---
title: Session Control Plane — Program Plan (v1 = human-relay spine)
type: feat
status: active
date: 2026-06-14
origin: docs/brainstorms/2026-06-14-autonomous-session-control-plane-requirements.md
---

# Session Control Plane — Program Plan (v1 = human-relay spine)

## Summary

Builds `hermes-claude-code-router` as a phased program. This plan locks the program's phase sequence
and load-bearing architecture decisions, then decomposes **v1 — the human-relay text spine** into
executable units; Phases B/C/D (observability, safety foundation, live autonomy) are roadmapped as named
follow-up plans with entry criteria. v1 turns the Phase-0 scaffold into a working router: connect to a
live Claude Code session from Discord, route text to it, relay replies back, and otherwise leave Mimir's
LLM untouched.

## Problem Frame

The repo is Phase-0 scaffold only — `protocol.py`, `plugin.yaml`, `PROTOCOL.md`, tests, and a
no-op `register(ctx)` stub at [__init__.py:21](../../plugins/hermes_claude_code_router/__init__.py). No
`router.py`, `redis_client.py`, `matchers.py`, `mode_state.py`, or `registry_reader.py` exists. The
[requirements doc](../brainstorms/2026-06-14-autonomous-session-control-plane-requirements.md) defines
the whole program (human-relay + autonomous, 30 reqs); the human-relay spine is its settled foundation
and the only part buildable without first resolving the autonomy-safety vocabularies or the cross-repo
task-state prerequisite.

## High-Level Technical Design

**The connector is a Hermes plugin** whose `register(ctx)` wires one hook and a set of slash commands,
then drives a Redis-streams bridge to live Claude Code sessions. Grounded in the verified Hermes
surface ([LEARNINGS#hermes-register-ctx-surface](../engineering-journal/LEARNINGS.md),
[#hermes-pre-gateway-dispatch-contract](../engineering-journal/LEARNINGS.md),
[#outbound-text-via-discord-py](../engineering-journal/LEARNINGS.md)): routing is decided in
`pre_gateway_dispatch` (returning `{"action": "skip"}` to suppress Mimir's LLM); outbound replies are
sent by reaching into `adapter._client.get_channel(id).send(...)` on the gateway loop.

**Program phase sequence (dependency-ordered — KTD1):**

| Phase | Scope | Depends on | This plan |
|-------|-------|------------|-----------|
| **A — human-relay spine (v1)** | presence/list, routing-target state, matchers, text bridge (DM/channel/thread), suppress-Mimir | the scaffold | **decomposed into U1–U8 below** |
| B — observability + agent tools | `task_state` (derived + worker markers), `session_status` read-tool, audit.jsonl spine | A + the cross-repo task-state prerequisite | follow-up plan |
| C — safety foundation (shadow) | deterministic gate, reversibility + R11a egress classifier, capability/ROE envelope, self-approval-as-verdict-source in **shadow** (log-only), kill switch | B | follow-up plan |
| D — live autonomy rungs | enable live self-approval (post-shadow-threshold), fire-and-check → supervise-and-approve → coordinate-toward-goal, correlation primitive, failure ladder (MRC, supervision, compensations) | C | follow-up plan |

v1 stops at Phase A: it is independently useful (hands-off-keyboard text routing), exercises the full
matcher → state → XADD-inbound → XREADGROUP-outbound → Discord pipeline, and the deferred autonomy
vocabularies (reversibility classes, envelope grammar, shadow threshold) are better resolved with the
spine in hand.

## Key Technical Decisions

- **KTD1 — Phase sequence A→B→C→D; v1 = Phase A (spine).** The spine is the foundation every later
  phase consumes, and is the only part with no unresolved-vocab or cross-repo blocker. Rejected
  "spine + eyes" as v1 because observability (B) carries the cross-repo task-state prerequisite that
  needs its own `infiquetra-claude-plugins` issue first.
- **KTD2 — Routing-target state in plugin memory.** Per [DECISIONS#routing-target-in-plugin-memory](../engineering-journal/DECISIONS.md);
  ephemeral per-conversation state, single-operator. Keyed `(user_id, endpoint, chat_id)`.
- **KTD3 — `protocol.py` stays byte-identical with redis-channel.** Per
  [DECISIONS#protocol-py-byte-identical](../engineering-journal/DECISIONS.md). v1 adds no protocol
  fields; it consumes the existing `Inbound`/`Outbound` models. Validate payloads against them; fail
  loud on mismatch.
- **KTD4 — Reach Discord via the adapter, not a gateway abstraction.** Capture `gateway` + `channel_id`
  in the hook; send outbound via `adapter._client.get_channel(id).send()` scheduled with
  `asyncio.run_coroutine_threadsafe` ([LEARNINGS#outbound-text-via-discord-py](../engineering-journal/LEARNINGS.md)).
  There is no `gateway.send_message()`.
- **KTD5 — Tests use fakeredis; Discord I/O is mocked at the unit level.** End-to-end (real Mimir +
  Redis + Discord) is a phase-level acceptance step, not a unit test ([pyproject.toml](../../pyproject.toml)
  dev-deps `fakeredis>=2.20`).
- **KTD6 — Voice is out; permission/autonomy is later.** Per [STRATEGY.md](../../STRATEGY.md) and
  [DECISIONS#dual-operator-autonomy-co-equal](../engineering-journal/DECISIONS.md): v1 speaks text only;
  the safety/autonomy program (Phases C/D) is roadmapped, not built here. The autonomy-safety
  vocabularies (reversibility classification, envelope grammar, shadow threshold) are deferred to the
  Phase C plan, which can resolve them empirically once the spine exists.

## Requirements

This plan satisfies the human-relay subset of the requirements doc. R-IDs map to that doc's reqs.

- R1. Connect/disconnect/list/switch routing-target state per `(user_id, endpoint, chat_id)`, in plugin
  memory, with routing on/off (requirements R1, R2, KTD2).
- R2. With a target set, operator text routes to the session's inbound stream and the session's replies
  relay back to the originating surface — DM, channel, thread (requirements R3).
- R3. With no target set, `pre_gateway_dispatch` returns `None` and Mimir's LLM behaves unchanged
  (requirements R4 — the no-regression guarantee).
- R4. `/cc list` (and the "list sessions" matcher) surfaces only live sessions from the registry,
  filtered by heartbeat (requirements R4-presence).
- R5. Inbound/outbound payloads validate against the byte-identical `protocol.py` models; a malformed
  payload is logged and dropped, never crashes the gateway (KTD3).

## Implementation Units

### U1. Redis client + connection helper

`plugins/hermes_claude_code_router/redis_client.py` — connect from `REDIS_URL` + URL-encoded
`REDIS_PASSWORD`; thin helpers for `XADD`, `XREADGROUP` (group `hermes-router`, create-if-missing),
`HGETALL`, `EXISTS`. Mirror the redis-channel `redis_client` pattern.

**Depends on:** none. **Satisfies:** R1–R5 (foundation).

**Test scenarios** (`tests/test_redis_client.py`, fakeredis): connect with password URL-encodes
special chars; `XADD`/`XREADGROUP` round-trips a message; consumer-group creation is idempotent
(second call no-ops); missing `REDIS_URL` raises a clear error.

### U2. Presence / registry reader

`plugins/hermes_claude_code_router/registry_reader.py` — `HGETALL cc-sessions:registry`, filter each by
`EXISTS cc-sessions:hb:<name>`, return live-session dicts (name, cwd-basename, git_branch, started_at,
last-seen-seconds). Lazy-ignore stale entries.

**Depends on:** U1. **Satisfies:** R4.

**Test scenarios** (`tests/test_registry_reader.py`): two registry entries, one with an hb key and one
without → only the live one returned; empty registry → `[]`; malformed registry JSON for one entry →
skipped with a log, others returned.

### U3. Routing-target state

`plugins/hermes_claude_code_router/mode_state.py` — in-memory dict keyed `(user_id, endpoint,
chat_id)`; `set_target`, `get_target`, `clear_target`, and routing on/off. No persistence (KTD2).

**Depends on:** none. **Satisfies:** R1.

**Test scenarios** (`tests/test_mode_state.py`): set→get returns the target; clear→get returns `None`;
two distinct keys do not collide; routing-off suppresses target resolution.

### U4. Matchers

`plugins/hermes_claude_code_router/matchers.py` — compile slash/regex patterns (connect, disconnect,
list, switch, mode-toggle) from plugin config, with a named capture for the session name; return a
structured match (intent + optional name) or `None`. Pattern config is read per-endpoint from
`plugin.yaml` (the master plan's host_vars shape: `connect_patterns` / `list_patterns` /
`disconnect_patterns` / `mode_phrases`), with built-in defaults when a key is unset.

**Depends on:** none. **Satisfies:** R1.

**Test scenarios** (`tests/test_matchers.py`): each canonical phrase matches its intent ("connect to
session foo" → connect+foo, "/cc list" → list, "switch to bar" → switch+bar); non-matching text →
`None`; case-insensitive; a config-overridden pattern matches; the session-name group rejects invalid
names.

### U5. Router hook (`pre_gateway_dispatch`)

`plugins/hermes_claude_code_router/router.py` — handler `(event, gateway=None, **_kw)`. **Capture
`gateway` into plugin state on first call** — the adapter and loop are only reachable from the event,
not at `register` time ([LEARNINGS#outbound-text-via-discord-py](../engineering-journal/LEARNINGS.md)).
Run matchers first → on a state-changing match, mutate `mode_state` and return `{"action": "skip",
"reason": ...}`; else if a target is set and the message is text → build an `Inbound` (derive `source`
from `event.message_type` = dm/channel/thread, `chat_id` from the surface id, `endpoint` from config;
validate against `protocol.py`), `XADD` to `cc-sessions:<target>:inbound`, return skip; else return
`None` (Mimir LLM responds). **Log every routing decision** (matched / routed→target / passed-through) —
the seed of the Phase-B audit spine, so the delivery-fidelity and fast-path-capture metrics can begin at
v1.

**Depends on:** U1, U3, U4, and `protocol.py`. **Satisfies:** R1, R2, R3, R5.

**Test scenarios** (`tests/test_router.py`): "connect to session foo" sets target + returns skip;
a text message with a target set → `XADD` to the right inbound stream with a valid `Inbound` payload +
returns skip; no target → returns `None`; "disconnect" clears the target; a payload that fails
`protocol.py` validation is logged and dropped, hook still returns cleanly.

### U6. Outbound relay

`plugins/hermes_claude_code_router/outbound.py` — a **per-target** supervised consumer, started when a
routing target is set **and** a gateway has been captured (U5), and stopped on disconnect (single-operator,
KTD2): `XREADGROUP GROUP hermes-router` on that target's `:outbound`; parse each as `Outbound`; send to
the originating surface via the captured adapter, **surface-aware** — guild channel via
`client.get_channel(chat_id)`, **DM via the user/DM channel (NOT `get_channel`, which returns `None` for
DMs)**, thread via the thread channel — scheduled with `asyncio.run_coroutine_threadsafe` on the gateway
loop; honor `in_reply_to` for threaded replies (KTD4). Exact discord.py calls per surface are confirmed
at implementation against the live adapter.

**Depends on:** U1, U5 (gateway capture), `protocol.py`. **Satisfies:** R2.

**Test scenarios** (`tests/test_outbound.py`, fakeredis + mock adapter): an outbound entry parses to
`Outbound` and routes to the right surface — **separate cases for guild-channel, DM, and thread** —
calling the surface-appropriate send with the right id + text; `in_reply_to` set → send includes the
reference; a malformed outbound is dropped with a log; send failure (channel `None` / DM not openable)
degrades gracefully without killing the loop; the consumer starts on target-set and stops on disconnect.

### U7. `register(ctx)` wiring + slash commands

`plugins/hermes_claude_code_router/__init__.py` — replace the stub: `ctx.register_hook(
"pre_gateway_dispatch", router_handler)`; `ctx.register_command("/cc list", ...)` plus connect /
disconnect / switch; **wire — but do not prematurely start — the U6 consumer**: it starts lazily once a
target is set and the hook has captured the gateway (U5/U6 lifecycle), since the gateway is unavailable
at load time. Load matcher/endpoint config from `plugin.yaml` (host_vars shape) with env overrides;
update `plugin.yaml` with the new config keys.

**Depends on:** U2, U5, U6. **Satisfies:** R1, R4.

**Test scenarios** (`tests/test_register.py`, mock `ctx`): `register(ctx)` registers the hook and each
slash command exactly once; `/cc list` handler returns the U2 live-session list formatted; missing
required env surfaces a clear load-time error (not a silent no-op).

### U8. Install script + CI wiring

Populate `scripts/install.sh` (adapt the `infiquetra-hermes-plugins` pattern: copy
`plugins/hermes_claude_code_router/` into `~/.hermes/plugins/`, pip-install `requirements.txt` into the
Hermes venv). Ensure the new tests run under the existing `.github/workflows/ci.yml`.

**Depends on:** U1–U7. **Satisfies:** deployability (requirements-doc install pattern).

**Test expectation:** none — scaffolding/tooling. (Optional: a shell lint / `--help` dry-run smoke
check.) CI already runs pytest + ruff + mypy; this unit only ensures the new modules are covered.

## Acceptance (v1 phase gate)

v1 is done when, against the real `mimir-engineer` profile + Redis (not just unit tests):

- From Discord, "connect to session <foo>" (or `/cc connect foo`) sets the target and Mimir's LLM does
  **not** also respond (skip works).
- A DM, a guild @mention, and a thread reply each route to the connected session, and the session's
  reply returns on the **same** surface.
- "disconnect" clears the target; subsequent messages go back to Mimir's LLM unchanged (the
  no-regression guarantee, R3).
- `/cc list` shows live sessions, and a killed session drops within the 60s heartbeat TTL.
- ruff + mypy + pytest (fakeredis units) green in CI.

This gate requires real Discord + Mimir interaction; unit tests mock the Hermes/Discord surface (KTD5).

## Scope Boundaries

**Out of scope for v1 (this plan):**

- Voice / TTS / Discord voice playback — upstream, per STRATEGY (permanently out of this connector).
- Any autonomous self-approval, task-state observability, kill switch, or orchestration — Phases B/C/D.
- LLM tools (`list_cc_sessions` etc.) — those serve the LLM-fallback routing of a later phase; v1 uses
  slash/regex matchers only.

**Deferred to follow-up work (named future plans, dependency-ordered):**

- **Phase B plan — observability + agent tools.** Entry criteria: v1 merged + used; the cross-repo
  task-state prerequisite filed in `infiquetra-claude-plugins` (worker-cooperative markers + the
  marker-carrying protocol field). Covers requirements-doc R5–R8, R25–R27, R29.
- **Phase C plan — safety foundation (shadow).** Entry criteria: Phase B observability working. Resolves
  the deferred vocab KTDs (reversibility classification + positive-allowlist, capability/ROE envelope
  grammar, shadow enable-threshold). Covers R9–R14, R11a, R28, R30.
- **Phase D plan — live autonomy rungs.** Entry criteria: Phase C shadow false-approval rate below the
  set threshold. Covers R15–R24.

## Risk Analysis & Mitigation

- **Hermes hook/adapter contract drift (Med).** v1 leans on `pre_gateway_dispatch`'s signature and the
  `adapter._client` reach, verified against `asgard_voice_arbiter` but not against the live
  `mimir-engineer` profile. *Mitigation:* U5/U6 isolate the Hermes-touching surface behind thin
  seams; the phase-level acceptance step runs against the real Mimir before declaring v1 done.
- **Cross-repo task-state prerequisite (Low for v1, High for Phase B).** v1 needs no protocol change, so
  it is unblocked; but Phase B cannot start until the `infiquetra-claude-plugins` worker-marker issue
  lands. *Mitigation:* file that issue at v1 merge so Phase B is not blocked on discovery.
- **Autonomy-safety risks are deferred, not absent (High, later).** The confidentiality/egress hole
  (R11a), the reversibility-classifier false-negative risk, and the operator-agent orchestration
  assumption all live in Phases C/D. *Mitigation:* the Phase C plan must run its own `/doc-review`;
  shadow-before-live (KTD6) is the structural gate that keeps these out of production until measured.
