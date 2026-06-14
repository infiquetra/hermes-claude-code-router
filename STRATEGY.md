---
name: hermes-claude-code-router
last_updated: 2026-06-14
---

# hermes-claude-code-router Strategy

## Target problem

You run multiple live Claude Code sessions and can only reach them one at a time at the
keyboard. A *running* session has no durable surface to operate it remotely and
conversationally, and none for an agent to drive it on your behalf — so neither hands-free
multiplexing by you nor autonomous coordination by an agent is possible today.

## Our approach

Keep the Claude Code worker **transport-agnostic behind a durable Redis bus**, and make this
connector the **operator↔session control plane**: it takes formatted text from an operator,
resolves routing/switching/orchestration intent, drives the right session(s), and relays
replies back. The same control plane serves a human-proxied operator and an autonomous one
interchangeably — how the operator was reached (voice, typed, Discord) stays upstream in the
agent, so the connector only ever sees text against a predetermined contract.

## Who it's for

**Primary (agent-as-customer):** The Hermes operator agent (Mimir) - it hires the connector to
discover which Claude Code sessions are live, route a formatted message to the right one, switch
the active target, and orchestrate work across several, over a durable bus without touching
Redis mechanics. Its job in one call: "given operator intent — the human's or my own — get the
right session driven and the reply back."

The **human is a customer of the agent, not of this connector** — deliberately out of scope. The
agent owns the human relationship; the connector owns the session-control relationship. Design
tradeoffs therefore optimize for **agent ergonomics** (machine-legible schemas, idempotent
switches, recoverable errors) over human-readable output.

## Key metrics

_None are measurable until the connector is built; all are instrumented in the router
decision-log / `audit.jsonl`. This section records which metrics matter and where they live._

- **Delivery fidelity** - share of operator messages that reach the *intended live session* and
  return a reply; misroutes, leaks to the agent's LLM when a target was set, and drops to
  dead/phantom sessions all count as failures.
- **Round-trip latency** - operator text → session → reply back.
- **Fast-path capture rate** - % of routing-intent messages resolved by regex/slash without LLM
  fallback (the matcher false-negative rate).
- **Autonomous goal-completion rate** - handed-off goals the agent lands without human
  intervention.
- **Permission false-approval rate** - autonomous approvals that should have been denied.

## Tracks

### Routing & orchestration control plane

The core: matchers, routing-target state, session switching, multi-session orchestration, and
the inbound/outbound Redis bridge — plus protocol & cross-repo stewardship (keeping `protocol.py`
byte-identical with `redis-channel`, the state-machine spec, contract tests, synchronized PRs).

_Why it serves the approach:_ it **is** the control plane, and the wire contract is the
decoupling that keeps the worker transport-agnostic.

### Agent operability

The surface the operator agent consumes: LLM tools (`list`/`set`/`get` target, session spawn),
machine-legible schemas, the predetermined text contract, and natural-language → routing
intelligence.

_Why it serves the approach:_ it invests directly in the primary customer — the agent — so an
operator can drive the connector correctly and recover from failure.

### Autonomy & safety

Permission relay (approve/deny over the bus), audit logging, and goal-coordination scaffolding —
the spine that lets the agent operate sessions unsupervised.

_Why it serves the approach:_ it's the second destination (autonomous operation), and becomes
foundational the moment the agent self-approves tool calls in your repos.

## Not working on

- **Operator-interface I/O (voice, Discord surfaces, typed input).** Upstream — owned by the
  Hermes agent; this connector only speaks text. Includes out-of-band TTS playback of replies.
- **Multi-user concurrent routing.** Single-operator for now; routing state stays in plugin memory.
- **Cross-WAN access (Tailscale) and alt-surface bridges (Telegram/iMessage/SMS).** Orthogonal.
- **Session-mode awareness/toggling from the operator side.** The channel protocol can't surface
  Claude Code's mode.
