# redis-bridge ↔ external-router protocol (v1)

This document is the canonical specification for the Redis-based protocol that connects a Claude Code session (running the `redis-bridge` channel plugin) to an external router/consumer (e.g., `hermes-claude-code-router`).

Both repos copy this file verbatim. Schema changes require synchronized PRs across both sides; the `v` field is bumped on any breaking change.

## Roles

- **CC plugin** (`redis-bridge`) — Claude Code channel running as an MCP subprocess of a Claude Code session. Hermes-agnostic. Speaks this protocol over Redis.
- **Router** (external) — anything that drives the conversation: `hermes-claude-code-router` is the reference implementation; alternatives could include a web UI, CLI test harness, or mobile app.

## Transport

- **Redis 6+** (consumer groups + Streams required).
- Connection: TCP, auth via `requirepass` or ACL. URL configured per-endpoint on each side.
- **Durable streams** for message-bearing channels; **pub/sub** for fire-and-forget lifecycle events.
- All payloads are JSON. All payloads MUST include `"v": 1`. Mismatched versions: log and drop; do not crash.

## Key namespace

All keys live under `cc-sessions:`:

| Key | Type | Purpose | TTL |
|---|---|---|---|
| `cc-sessions:registry` | Hash | Static session metadata, field-per-session | None (lazy GC) |
| `cc-sessions:hb:<session_name>` | String | Heartbeat presence indicator | 60s, refreshed every 10s |
| `cc-sessions:<session_name>:inbound` | Stream | Messages from router → CC | MAXLEN ~10000 |
| `cc-sessions:<session_name>:outbound` | Stream | Replies from CC → router | MAXLEN ~10000 |
| `cc-sessions:<session_name>:permission_request` | Stream | CC asks for tool approval | MAXLEN ~1000 |
| `cc-sessions:<session_name>:permission_verdict` | Stream | Router answers approval request | MAXLEN ~1000 |
| `cc-sessions:events:<session_name>` | Pub/sub channel | Lifecycle and mode events | n/a |

Consumer groups:
- CC reads inbound + permission_verdict via group `cc:<session_name>` (consumer name `consumer-1`, single consumer per session).
- Router reads outbound + permission_request via group `<router-name>` (e.g., `hermes-router`).

## Presence

### Registration (CC on `/redis-bridge connect`)

```
HSET cc-sessions:registry <session_name> <static_metadata_json>
SET  cc-sessions:hb:<session_name> <iso_timestamp> EX 60
```

Static metadata payload:

```json
{
  "v": 1,
  "session_name": "infiquetra-claude-plugins-a3f7",
  "host": "jeffs-laptop.local",
  "cwd": "/Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins",
  "git_branch": "feature/redis-bridge-scaffold",
  "pid": 12345,
  "started_at": 1716567890.123,
  "capabilities": ["reply", "permission", "askuserquestion_intercept"]
}
```

### Heartbeat

CC writes the hb key every 10s with `EX 60`. Six consecutive missed beats causes presence expiry. Session metadata in `cc-sessions:registry` stays in place (lazy GC); routers MUST filter by `EXISTS cc-sessions:hb:<session_name>` before treating an entry as live.

### Graceful disconnect (CC on `/redis-bridge disconnect`, SIGTERM, SIGINT)

```
DEL  cc-sessions:hb:<session_name>
HDEL cc-sessions:registry <session_name>
PUBLISH cc-sessions:events:<session_name> {type:"unregistered", reason:"graceful", ts:...}
```

### Ungraceful disconnect

Hb key expires after 60s of no refresh. Router sees missing hb on next list operation; emits `unregistered{reason:"timeout"}` on the events pub/sub channel.

## Inbound (router → CC)

```
XADD cc-sessions:<session_name>:inbound *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "router": "hermes-claude-code-router",
  "endpoint": "mimir",
  "source": "voice | dm | channel | thread",
  "chat_id": "<external-context-id, opaque to CC>",
  "user_id": "<external-user-id, opaque to CC>",
  "username": "<display name for the human>",
  "text": "<message body, already transcribed if voice>",
  "confidence": 0.93,
  "ts": 1716567890.123,
  "metadata": {}
}
```

CC consumes via:

```
XREADGROUP GROUP cc:<session_name> consumer-1 BLOCK 1000 STREAMS cc-sessions:<session_name>:inbound >
```

CC emits `notifications/claude/channel` to the Claude Code session with content:

```
<channel source="redis-bridge" router="hermes-claude-code-router" endpoint="mimir"
         source_type="voice|dm|channel|thread" chat_id="..." user="..." username="..."
         confidence="0.93" ts="...">
<text body>
</channel>
```

CC `XACK`s on successful emission.

## Outbound (CC → router)

Claude calls the `reply` MCP tool. CC writes:

```
XADD cc-sessions:<session_name>:outbound *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "session_name": "infiquetra-claude-plugins-a3f7",
  "endpoint": "mimir",
  "chat_id": "<reply target, mirrored from inbound>",
  "text": "<reply body>",
  "voice": true,
  "in_reply_to": "<optional inbound stream ID for threading>",
  "ts": 1716567890.123
}
```

Router consumes via `XREADGROUP GROUP <router_name> consumer-1 BLOCK 1000 STREAMS ...:outbound >` and delivers via its native channel (Discord DM, voice channel, etc).

## Permission relay

### Request (CC → router)

When Claude Code core emits `notifications/claude/channel/permission_request`, CC writes:

```
XADD cc-sessions:<session_name>:permission_request *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "session_name": "infiquetra-claude-plugins-a3f7",
  "endpoint": "mimir",
  "request_id": "abcde",
  "tool_name": "Bash",
  "input_preview": "git push origin main",
  "description": "Push to remote",
  "destructive": true,
  "originating_chat_id": "<chat_id that started this routing>",
  "ts": 1716567890.123
}
```

`request_id` is the 5-char id supplied by Claude Code core (not generated by CC).

`destructive` is `true` when:
- `tool_name` is one of `Write`, `Edit`, `NotebookEdit`
- `tool_name` is `Bash` AND `input_preview` matches one of the destructive regex patterns in `protocol.py`

### Verdict (router → CC)

Router collects user response (within `permission_window_seconds`, default 30) and writes:

```
XADD cc-sessions:<session_name>:permission_verdict *  payload <JSON>
```

Payload:

```json
{
  "v": 1,
  "session_name": "infiquetra-claude-plugins-a3f7",
  "endpoint": "mimir",
  "request_id": "abcde",
  "verdict": "allow | deny",
  "source": "voice | dm | channel | thread | timeout",
  "voice_confidence": 0.91,
  "echo_confirm_outcome": "passed | cancelled | not_required",
  "ts": 1716567890.456
}
```

CC consumes via its `cc:<session_name>` group and emits `notifications/claude/channel/permission` to Claude Code core.

`echo_confirm_outcome` is `passed` if a destructive request's 3-second cancel window elapsed silently; `cancelled` if "cancel" was heard within the window; `not_required` for non-destructive requests.

## AskUserQuestion interception

`AskUserQuestion` is a Claude Code tool that surfaces structured multi-choice UI on the terminal. The channel protocol does not natively support structured questions.

**The CC plugin intercepts the tool call** before it reaches the user. When Claude calls `AskUserQuestion` from a channel session:

1. CC plugin's MCP server intercepts the tool invocation.
2. Renders the structured question as inline text (markdown), routed through the `reply` tool with `voice=False` (if mode permits) or both `voice=True` + text per the originating source:

   ```
   I need to make a decision. Please reply with one of these options:

   **Which approach should I take?**
   - **A)** Use a connection pool — faster, more complex
   - **B)** Open per-request — simpler, slower
   - **C)** Cache results — fastest, stale data risk

   Reply with the letter (A, B, or C), or describe your choice in your own words.
   ```

3. CC parses the user's next inbound message and matches against options (letter, label substring, free-text).
4. CC returns the matched answer to the `AskUserQuestion` caller as the tool result.

This is implemented in MCP server middleware, not via agent-file coaching. Behavior is deterministic regardless of Claude's training.

## Lifecycle events (pub/sub)

```
PUBLISH cc-sessions:events:<session_name> <JSON>
```

Event types:

| Type | Direction | Payload extras |
|---|---|---|
| `registered` | CC → router | `static_metadata` |
| `unregistered` | CC → router (graceful) OR router → router (timeout) | `reason: "graceful" \| "timeout"` |
| `mode_change` | router → CC | `mode: "normal"|"routing"`, `endpoint`, `reason` |
| `routing_target_changed` | router → CC | `endpoint`, `new_target: "<session_name>"|null`, `reason: "user_phrase"|"slash"|"llm_tool"` |
| `presence_ping` | either way | `who: "cc"|"router"` |

Both sides subscribe to relevant channels. Pub/sub is at-most-once; do not rely on it for state — use streams for durable handoffs.

## Versioning and compatibility

- All payloads carry `v: 1`.
- Adding optional fields is backwards-compatible; routers/CC MUST ignore unknown fields.
- Removing or repurposing fields requires `v` bump and synchronized release.
- The `pydantic` models in `server/protocol.py` (CC) and `hermes_claude_code_router/protocol.py` (router) are the enforcement layer. Both repos validate inbound payloads strictly.

## Reserved future expansion

- `notifications/claude/channel/question_request` — IF Claude Code adds it natively, this protocol grows a `question_request`/`question_verdict` stream pair and the AskUserQuestion interception is replaced by passthrough.
- Mode awareness — IF Claude Code exposes session mode, add a `mode_state` lifecycle event.
- Multi-router-per-session — currently 1 session : 1 router consumer group. Could grow to a fanout model.
