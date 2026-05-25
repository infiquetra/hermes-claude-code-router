# Routing-target state machine

This document specifies how the **router** side (e.g., `hermes-claude-code-router`) decides whether an inbound user message gets routed to a Claude Code session or handled by the router's own LLM (e.g., Mimir's normal LLM). The CC plugin is stateless about this — it just emits whatever it receives.

The state machine is owned by the router. This spec exists so any router implementation behaves consistently.

## State key

The routing decision is keyed by a tuple:

```
(user_id, endpoint, chat_id)
```

- `user_id`: the external system's user identifier (e.g., Discord user ID).
- `endpoint`: the router-side endpoint name (e.g., `mimir`).
- `chat_id`: the conversation surface (Discord DM ID, voice channel ID, thread ID, etc).

Each tuple is an independent routing state. Two simultaneous conversations between the same user and the same endpoint on different surfaces (DM + voice) are independent.

## State values

```
State {
  target: session_name | null   # which CC session this conversation routes to
  routing_enabled: bool          # has the user explicitly said "start coding session"?
  set_at: timestamp              # last transition
  set_by: "slash" | "regex" | "llm_tool" | "user_phrase" | "timeout"
}
```

Defaults (no entry exists): `target=null`, `routing_enabled=false`. Equivalent to "router's normal LLM handles everything for this (user, endpoint, chat_id)."

Routing happens **only when both** `target != null` AND `routing_enabled == true`.

## Transitions

```
                   ┌──────────────────────────────────────┐
                   │  no entry (default)                  │
                   │  target=null, routing_enabled=false  │
                   └──────────────────────────────────────┘
                         │                  │
       connect verb /    │                  │  "start coding session" phrase
       slash match       │                  │  (no target set yet → no-op + hint)
                         ▼                  │
                   ┌──────────────────────┐ │
                   │ target set,          │ │
                   │ routing_enabled=false│◀┘
                   └──────────────────────┘
                         │ ▲
   "start coding         │ │  "end coding session" /
    session"             │ │  "stop routing"
                         ▼ │
                   ┌──────────────────────┐
                   │ target set,          │
                   │ routing_enabled=true │ ◀── ALL INBOUND MESSAGES ROUTE TO CC
                   └──────────────────────┘
                         │
   disconnect /          │
   target=null           │
                         ▼
                   ┌──────────────────────────────────────┐
                   │  no entry (back to default)          │
                   └──────────────────────────────────────┘
```

## Trigger sources

The router scans every inbound message (text or transcribed voice) in priority order:

1. **Slash command** (`/cc connect <name>`, `/cc disconnect`, etc) — exact prefix match. Takes effect immediately, no LLM involvement.
2. **Regex pattern** (configurable per endpoint) — e.g., `connect to (?:session|cc)\s+(?P<name>\S+)`, `list sessions`, `start coding session`, `end coding session`. Takes effect immediately.
3. **LLM tool fallback** — if neither slash nor regex matched AND the message contains keywords suggesting session intent (`session`, `claude code`, `connect`, `switch`, `work on`, `feature`, `branch`, `yesterday`), the router hands the message to its own LLM (e.g., Mimir) with the registered tools (`list_cc_sessions`, `set_routing_target`, `get_routing_target`). The LLM decides whether to call a tool or respond normally.

If none of the above triggers fire AND `routing_enabled` is true AND `target` is set, the message is forwarded to the CC session via XADD inbound.

If none fire AND routing is not enabled-and-targeted, the message goes to the router's normal LLM path.

## Concrete transition table

| Current state | Trigger | New state | Side effects |
|---|---|---|---|
| any | slash `/cc connect <name>` | `target=<name>, routing_enabled=current_value` | Confirm "Connected to <name>." Publish `routing_target_changed`. |
| any | regex "connect to session <name>" / "switch to <name>" | same as above | same |
| any | LLM tool `set_routing_target(name)` | same as above | same |
| target set | slash `/cc disconnect` | `target=null, routing_enabled=false` (delete entry) | Confirm "Disconnected." Publish `routing_target_changed{new_target:null}`. |
| target set | regex "disconnect" / "stop routing" + no target name | same | same |
| target set, routing off | regex "start coding session" | `routing_enabled=true` | Confirm "Routing to <target>." Publish `mode_change{mode:"routing"}`. Suppress LLM. |
| target set, routing on | regex "end coding session" / "stop routing" | `routing_enabled=false` | Confirm "Mimir back." Publish `mode_change{mode:"normal"}`. Suppress LLM. |
| no target | regex "start coding session" | unchanged | Hint via reply: "No session selected; say 'connect to session <name>' first or 'list sessions'." |
| target set, routing on | normal inbound (no trigger match) | unchanged | XADD inbound to `cc-sessions:<target>:inbound`. Suppress router LLM via `{"action":"skip"}`. |
| target unset OR routing off | normal inbound | unchanged | Router LLM handles normally (no XADD). |

## Race conditions and resolution

### R1: Slash and routing-on phrase in the same message

> User says: "/cc connect foo and start coding session"

Slash command takes priority (first scan). After slash sets `target=foo`, the regex scan in the same pass sees "start coding session" and toggles `routing_enabled=true`. Two transitions; one confirmation reply combining both ("Connected to foo. Routing to foo.").

### R2: Simultaneous DM and voice messages on the same (user, endpoint)

> User has a DM open AND is in a voice channel. State `(user, endpoint, dm_chat_id)` and `(user, endpoint, voice_chat_id)` are **independent**. Each gets its own routing state. Connecting on voice does not affect DM, and vice versa.

This is intentional: it lets you have a long voice routing session while also DMing Mimir for one-off questions.

### R3: Permission request mid-stream, user is also speaking

Router state: `target=foo, routing_enabled=true`. CC emits a permission request. Router speaks the prompt. User says "yes abcde" — does this go through routing (XADD inbound) OR get parsed as the permission verdict?

**Resolution**: permission window claim is **scoped to the originating chat_id and active for `permission_window_seconds`**. While active for chat_id X, all inbound messages on chat_id X are first checked against `yes <id>` / `no <id>` / `cancel` patterns; non-matching messages route normally. Matched messages are consumed by the permission relay and NOT forwarded to CC inbound.

### R4: New `set_routing_target` while a permission request is pending

Router state: target=foo, routing_enabled=true, permission request pending for request_id=abcde. User says: "/cc connect bar".

**Resolution**: slash command takes priority over pending permission. Pending request is **denied with reason=`target_changed`** and a `permission_verdict` is emitted. Then target changes to bar. User is informed: "Disconnected from foo (with pending approval denied). Connected to bar."

### R5: Heartbeat expires for the current target mid-routing

Router observes that `EXISTS cc-sessions:<target>:hb` returns 0. The CC session is gone.

**Resolution**: router immediately resets `target=null, routing_enabled=false` for ALL `(user, endpoint, chat_id)` states pointing to that target. Publishes `routing_target_changed{new_target:null, reason:"target_lost"}`. Surfaces a notification: "Session <target> disconnected; routing off."

### R6: Two users routing through the same endpoint

User A and User B both interact with Mimir. State keys are `(A, mimir, ...)` and `(B, mimir, ...)` — fully independent. User A can be routing to session foo while User B is routing to session bar OR using Mimir normally.

Two users routing to the **same** target is allowed by this state machine (each user has their own routing state) but produces interleaved inbound messages on the same stream. The CC session sees both as separate `<channel>` events with different `user_id`/`username`. CC + Claude handle the multi-user case at the application layer (likely by Claude noticing context shifts).

## Persistence

- Routing state is held **in memory** in the router process.
- Persisted to a JSON file (e.g., `~/.hermes/plugins/hermes_claude_code_router/state.json`) on every transition.
- Loaded on router startup. Stale targets are validated against the live registry on load; targets without a live hb key are reset to null.

## Out of scope for v1

- Cross-user "borrow my session" handoff (would need explicit transfer semantics).
- Per-message routing override ("Mimir, what's the time" inside a routing session).
- Time-window auto-disconnect (inactivity timeout).
- Multiple targets per (user, endpoint, chat_id) tuple (fanout).
