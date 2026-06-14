# Learnings — `hermes-claude-code-router`

> **Empirical findings + mechanisms + fixes + validations.** When something turns out to be true that wasn't obvious — about Hermes plugin loading, hook contracts, voice pipeline shapes, deploy mechanisms, integration points with `redis-channel` — it goes here. Include the **evidence** (PR / commit / file:line / reproduction recipe) and the **mechanism** (why it's true), not just the observation.
>
> **Append new entries to the top.** Most-recent first. Format:
>
> ```markdown
> ## YYYY-MM-DD
>
> ### Short descriptive title  {#slug}
>
> **Context.** One paragraph framing the situation.
> **Evidence.** Specific PR / commit / file:line / reproduction recipe.
> **Mechanism.** Why it happened (or why it's true) — root cause, not just symptoms.
> **Fix (or queued).** Concrete action + commit hash, OR a QUEUED.md ref if deferred.
> **Validation (if applicable).** What later run / test / install proved the fix.
> **What surprised (optional).** The thing that wasn't in the original mental model.
> **Generalizable rule.** The lesson stripped of this specific incident — what would I tell a future-me hitting a similar shape?
> **Refs.** Cross-links to DECISIONS / QUEUED / narratives / other LEARNINGS entries.
> ```

---

## 2026-06-14

### Claude Code surfaces no native turn-complete/error signal to a channel plugin  {#no-native-task-state-signal}

**Context.** Planning the autonomy observability axis — whether an operator agent can see a session's task-state (idle/working/blocked/completed/errored) — required knowing what lifecycle signal Claude Code actually exposes to a channel/MCP plugin.

**Evidence.** Verification against the `redis-channel` plugin (`server/channel.py`) + the Claude Code channel/hooks surface (this session, 2026-06-14): a channel plugin receives only `notifications/claude/channel` (inbound), `.../permission_request`, and `.../permission`. There is no turn-complete / idle / session-error notification. So: blocked-on-permission is observable (the permission stream); working/idle is derivable (inbound-dispatched vs outbound-reply-arrived); completed-goal-vs-mid-task and errored are NOT natively observable.

**Mechanism.** Claude Code's channel notification surface carries message + permission events only; turn/session lifecycle is not exposed to plugins — and that surface is Anthropic's, not ours to extend.

**Fix (or queued).** Task-state observability uses a HYBRID: derive what the existing streams allow; require **worker-cooperative markers** (the session emits explicit task-state via the reply tool, coached) for completed/blocked-mid-task/errored. Captured in the requirements doc (R5/R28) and the Phase B roadmap; CC-side marker support is a cross-repo prerequisite (an `infiquetra-claude-plugins` issue). See [DECISIONS#phase-sequence-v1-spine](DECISIONS.md#phase-sequence-v1-spine).

**What surprised.** Ideation reframed "task-state is just uninstrumented" as easily addable; verification showed the missing half can't be added on our side at all — it needs worker cooperation, not a CC-side hook.

**Generalizable rule.** Before building observability on a platform signal, verify the platform actually emits it to your integration point; if it doesn't and the surface isn't yours, design for cooperative self-reporting from the component you DO control, not a hoped-for upstream hook.

**Refs.** [requirements R5/R28](../brainstorms/2026-06-14-autonomous-session-control-plane-requirements.md); [doc-review P1-2](../reviews/2026-06-14-autonomous-session-control-plane-doc-review.md).

---

## 2026-05-26

> The entries below were captured during the `redis-channel` plugin build (companion repo `infiquetra/infiquetra-claude-plugins`) when investigating how the router would interact with Hermes. They predate any router code; they're foundational context for the next session that picks up the router build. See the related narrative: [`narratives/2026-05-26-router-build-plan.md`](narratives/2026-05-26-router-build-plan.md).

### Hermes `register(ctx)` API surface for plugin authors  {#hermes-register-ctx-surface}

**Context.** The router (this plugin) needs to register a hook (`pre_gateway_dispatch`) + multiple LLM tools (`list_cc_sessions`, `set_routing_target`, `get_routing_target`) + slash commands (`/cc connect`, `/cc list`, `/cc disconnect`). Figuring out the exact `ctx` API was the first investigation in the router build prep.

**Evidence.** `~/workspace/infiquetra/infiquetra-hermes-plugins/docs/plugin-authoring.md:49-58` documents the API surface. Verified via several plugins in `~/workspace/infiquetra/infiquetra-hermes-plugins/plugins/` + the `home-lab` deployed plugin at `~/workspace/infiquetra/home-lab/ansible/roles/hermes/files/plugins/asgard_voice_arbiter/__init__.py`.

| Method | Purpose |
|--------|---------|
| `ctx.register_hook(name, callable)` | Register a lifecycle hook callback (e.g., `pre_gateway_dispatch`, `pre_tool_call`) |
| `ctx.register_tool(name, schema, handler)` | Register an LLM-available tool (JSON Schema, Claude tool-use protocol) |
| `ctx.register_command(name, handler, description)` | Register a `/name` slash command |
| `ctx.register_cli_command(name, help, setup, handler)` | Register a `hermes <name>` CLI subcommand |
| `ctx.register_skill(name, path)` | Bundle a skill for `skill_view()` |
| `ctx.inject_message(content, role="user")` | Push a message into the active session (CLI mode only; returns False in gateway mode) |

`ctx` is provided to the plugin's `register(ctx)` entry point at load time. The plugin's `__init__.py:register(ctx)` is called once when Hermes discovers + loads the plugin from `~/.hermes/plugins/<name>/`.

**Mechanism.** Hermes's plugin loader scans `~/.hermes/plugins/`, imports each plugin package, looks up its `register(ctx)`, and calls it with a context object that wires the plugin into Hermes's various subsystems (hook registry, tool registry, slash dispatcher, etc.). The plugin doesn't subclass anything — it's procedural registration.

**Canonical template.** `~/workspace/infiquetra/infiquetra-hermes-plugins/plugins/security_guidance/` is the simplest real example: registers a `pre_tool_call` hook, has tests, ~50-line `__init__.py`. Use it as the file-layout starter.

**What surprised.** No TTS/STT mention in the plugin authoring surface — those are SEPARATE plugin types via `ctx.register_tts_provider(...)` (per [hermes-agent.nousresearch.com/docs/user-guide/features/tts](https://hermes-agent.nousresearch.com/docs/user-guide/features/tts)). For us, that's only relevant if we end up writing a TTS provider plugin (we're not — voice-forge already is one); the router is a different plugin type using the hook + tool surface.

**Generalizable rule.** For any Hermes plugin work: read `infiquetra-hermes-plugins/docs/plugin-authoring.md` first; then find the closest existing plugin in `infiquetra-hermes-plugins/plugins/` AND in the deployed plugins at `~/workspace/infiquetra/home-lab/ansible/roles/hermes/files/plugins/`. The home-lab ones often have more real-world hook-handler shapes than the docs.

**Refs.** Companion repo `infiquetra/infiquetra-claude-plugins`. Plugin manifest fields documented at [#hermes-plugin-manifest](#hermes-plugin-manifest).

---

### `pre_gateway_dispatch` hook contract (verified against `asgard_voice_arbiter`)  {#hermes-pre-gateway-dispatch-contract}

**Context.** The router's primary integration point. Need to know: exact signature, what attributes the `event` argument exposes, what return values short-circuit Mimir's LLM.

**Evidence.** `~/workspace/infiquetra/home-lab/ansible/roles/hermes/files/plugins/asgard_voice_arbiter/__init__.py:493-559`.

**Signature:**

```python
def _on_pre_gateway_dispatch(event, gateway=None, **_kw):
    ...
```

**Parameters:**
- `event` — inbound gateway message object with attributes:
  - `message_type` (str) — `"voice"`, `"text"`, etc.
  - `text` (str) — message content
  - `source` (obj) — nested with `.user_id`, `.author_id` (alias), `.channel_id`
  - `channel_id`, `guild_id` may also be top-level (asgard_voice_arbiter:452 reads both shapes)
- `gateway` — Hermes gateway reference; captured opportunistically for downstream async work
- `**_kw` — absorb other kwargs for forward compatibility

**Return values:**
- `None` — allow normal dispatch (default behavior)
- `{"action": "skip", "reason": "<string>"}` — suppress Mimir's LLM response, halt further dispatch
- `{"action": "allow"}` — explicitly allow (semantically equivalent to `None`)

The router will use `{"action": "skip"}` when it routes a message to a CC session (so Mimir's LLM doesn't ALSO respond).

**When it fires.** Before auth/pairing, before the LLM loop; runs in-process. Plugins can capture `gateway` synchronously and use it for downstream out-of-band sends.

**Generalizable rule.** For routing decisions, `pre_gateway_dispatch` is the canonical hook. `pre_tool_call` is for tool-execution guards. There is no separate `pre_voice_dispatch` hook — voice and text come through the same `pre_gateway_dispatch` and are distinguished by `event.message_type`.

**Refs.** Voice path detail at [#voice-via-pre-gateway-dispatch](#voice-via-pre-gateway-dispatch). Outbound send detail at [#outbound-text-via-discord-py](#outbound-text-via-discord-py).

---

### Voice transcripts come through the SAME `pre_gateway_dispatch` hook (not a separate one)  {#voice-via-pre-gateway-dispatch}

**Context.** Master plan called for "Hermes plugin: hook into transcript stream from Mimir's existing voice pipeline." Initial assumption was a separate `on_voice_transcript` event. Reality: voice and text both flow through `pre_gateway_dispatch`.

**Evidence.** `asgard_voice_arbiter/__init__.py:504` sets `is_voice_msg = "voice" in str(event.message_type).lower()`. Same plugin processes both surfaces; the differentiation is purely the `message_type` attribute on the event.

**Event shape for voice transcripts:**
```
event.message_type       # "voice" for transcripts
event.text               # The transcript string (post-STT)
event.source             # Sub-object:
  .user_id               # Discord user ID
  .channel_id            # Voice channel ID
event.channel_id         # Also at top level in some shapes
event.guild_id           # Guild ID
```

Notable: **NO `message_id` on voice transcripts** (they're STT outputs, not Discord text messages). Router will synth its own correlation handle (e.g., `f"{guild_id}:{voice_channel_id}:{user_id}:{ts}"`).

**Generalizable rule.** For the router's hook handler: filter by `event.message_type` to split voice vs. text behavior. Voice gets routing-on/off toggle phrase matching ("start/end coding session") AND, if routed-on, XADD to inbound. Text gets the regex/slash matchers for `/cc connect <name>` etc.

**Refs.** STT-confidence limitation at [#stt-confidence-not-propagated](#stt-confidence-not-propagated). Mimir profile config at [#mimir-profile-config-location](#mimir-profile-config-location).

---

### STT confidence is NOT propagated to plugin hooks  {#stt-confidence-not-propagated}

**Context.** Master plan called for confidence-threshold voice approval. Wanted to know if confidence reaches the plugin layer.

**Evidence.** `asgard_voice_arbiter/__init__.py:434-476` defensively searches multiple attribute names (`user_id`, `author_id`, `sender_id` — and similar for confidence) but finds no `confidence` field. The faster-whisper STT pipeline produces confidence internally but Hermes doesn't surface it on the event.

**Mechanism.** Hermes's templating between STT output → gateway event doesn't include confidence. Verifying by reading `hermes-agent/gateway/` upstream might reveal a way to opt into it, but the docs don't document one.

**Workaround per master plan.** Accept transcripts unconditionally. If low-quality transcripts reach a routed CC session, Claude will ask for clarification naturally. For permission relay (Phase 4 deferred), the voice-approval confidence threshold called for in the plan can't be implemented today; either degrade to "accept any matched 'yes/no <id>' phrase" or wait until upstream surfaces confidence.

**Generalizable rule.** When a documented voice/STT feature relies on a signal that turns out to be unsurfaced: degrade gracefully + flag the gap. Don't fake the signal.

**Refs.** Permission-relay implications in [QUEUED](QUEUED.md#permission-relay-voice-deferred).

---

### No `gateway.send_message()` API — outbound goes via `adapter._client.get_channel(id).send(text)`  {#outbound-text-via-discord-py}

**Context.** The router's XREADGROUP loop produces outbound replies that need to land in Discord (channel send for text, or TTS-played in voice channel — voice deferred). Question: what API call from the plugin produces the send?

**Evidence.** Investigation of `asgard_voice_arbiter/__init__.py:273-378`. The gateway reference doesn't expose a `send_message()` method. Pattern:

```python
adapter = _get_discord_adapter(gateway)  # gateway.adapters["discord"]
client = getattr(adapter, "_client", None) or getattr(adapter, "client", None)
channel = client.get_channel(channel_id)
await channel.send(text)  # Discord.py's built-in
```

The send is scheduled on the gateway's asyncio loop:
```python
loop = _get_loop(gateway)  # gateway.loop, _loop, or asyncio.get_event_loop()
asyncio.run_coroutine_threadsafe(async_func(adapter, ...), loop)
```

**Mechanism.** Hermes's gateway is a thin orchestrator around platform adapters (`gateway.adapters["discord"]`). The plugin reaches into the adapter to get the underlying `discord.py` client, then uses standard `discord.py` async APIs. The gateway doesn't try to be a transport abstraction — it exposes the underlying adapter for plugins to use.

**Implication for the router's XREADGROUP loop.** Capture `gateway` + the `event`'s `channel_id` (text channel for DM/mention, voice channel for TTS playback) in `pre_gateway_dispatch`. Store the mapping `(session_name, chat_id) → (gateway, channel_id)` in plugin state. When the XREADGROUP loop produces an outbound payload, look up the channel_id, get the channel, call `.send(text)` (or `.play(audio)` for voice).

**Generalizable rule.** Hermes plugins are NOT abstracted away from platform internals. Reaching into `adapter._client` and using `discord.py` (or telegram, or whatever) directly is the EXPECTED pattern. Don't try to find a higher-level gateway send API — there isn't one.

**Refs.** Voice playback pattern at [#out-of-band-voice-pattern](#out-of-band-voice-pattern).

---

### For out-of-band TTS (router XREADGROUP outbound with `voice=true`): synth + play ourselves  {#out-of-band-voice-pattern}

**Context.** When the CC plugin's `reply` tool produces an outbound with `voice=true`, the router needs to play the text as TTS in the originating voice channel. Initial confusion: does Hermes auto-TTS our reply because the originating event was voice?

**Evidence (clarification from Jeff).** Hermes auto-TTSes only for **its own LLM response path** (Mimir LLM responds to voice → Hermes pipes through configured TTS provider → played in voice channel). Plugin out-of-band messages (sent via `channel.send` or `voice_client.play`) do NOT trigger that pipeline. Two options:

1. **Use Hermes's TTS provider plugin pattern** — register a `TTSProvider` and let Hermes do everything. But: that requires the response to flow through Mimir's LLM path, which we DON'T want (the response came from a CC session, not Mimir's LLM).

2. **Synth ourselves, play via discord.py.** Voice-forge already runs at TCP `:9876` on `jeffs-mac-mini` (per the home-lab Phase G cutover). HTTP `POST /v1/audio/speech` returns WAV/Opus bytes. Then `voice_client.play(discord.FFmpegPCMAudio(...))` plays it.

**Per Jeff:** "I would look at our voice-forge... but we could simply use edge tts for now, if voice-forge isn't deployed yet." Mimir currently uses Edge TTS (`en-GB-RyanNeural`), NOT voice-forge — see [#mimir-profile-config-location](#mimir-profile-config-location). voice-forge IS deployed (the 4 NeuTTS sisters use it) but Mimir's profile rejected ElevenLabs day-one + uses Edge TTS as v1.

**Mechanism + Phase ordering decision.** Voice support is deferred until voice-forge is a first-order Hermes provider AND we've shipped the text-only router (so we know the routing semantics work before adding the synth+play layer). See [DECISIONS#voice-deferred-until-voice-forge-first-order](DECISIONS.md#voice-deferred-until-voice-forge-first-order).

**Generalizable rule.** "Hermes auto-TTSes voice responses" is true ONLY for responses flowing through its LLM pipeline. Out-of-band plugin sends bypass that. Plan accordingly: either route through Mimir's LLM (won't work for the router because we deliberately suppress Mimir's LLM via `{"action": "skip"}`), or synth+play yourself.

**Refs.** voice-forge integration deferred to [QUEUED#voice-forge-http-integration](QUEUED.md#voice-forge-http-integration). Discord voice playback deferred to [QUEUED#discord-voice-playback](QUEUED.md#discord-voice-playback). Phase ordering at [DECISIONS#text-chat-first-milestone](DECISIONS.md#text-chat-first-milestone).

---

### Mimir profile config lives in Ansible host_vars, NOT `~/.hermes/profiles/mimir/`  {#mimir-profile-config-location}

**Context.** Master plan said "Mimir profile bootstrap — `~/.hermes/profiles/mimir/` doesn't exist yet". Reality: that path doesn't exist by design. Mimir runs as `mimir-engineer` profile on `jeffs-mac-mini.infiquetra.com`, configured via Ansible.

**Evidence.** `~/workspace/infiquetra/home-lab/ansible/inventory/host_vars/jeffs-mac-mini.infiquetra.com.yml` (commit `c457d29` on `feature/mimir-engineer-profile`). Mimir-specific env vars:
```yaml
AGENT_NAME=mimir
ASGARD_AUTO_JOIN_VC_ID=1508449251472969950  # Mímisbrunnr channel
ASGARD_VOICE_ALWAYS_RESPOND=true
```
Persona file at `~/workspace/infiquetra/home-lab/ansible/roles/hermes/files/souls/mimir.md`.

**Key facts:**
- Profile name: `mimir-engineer` (not `mimir`)
- Voice channel: **Mímisbrunnr** (`1508449251472969950`) — Mimir's own VC, NOT the shared Asgard Voice channel
- TTS: **Edge TTS** with `en-GB-RyanNeural` (British male) — NOT voice-forge
- LLM: `gpt-5.5` with `reasoning_effort: high`
- Discord guild: Asgard (Mimir moved from Mount Olympus → Asgard on 2026-05-25)

**Mechanism.** Hermes profiles are templated by Ansible at deploy time. `host_vars/<host>.yml` declares profile env + skills + voice config; `roles/hermes/` renders the runtime config under `~/.hermes/profiles/<profile-name>/`. The router plugin reads runtime values via Hermes's own env-loading; it doesn't reach into host_vars.

**Generalizable rule.** Before assuming a Hermes-state location, check `~/workspace/infiquetra/home-lab/ansible/inventory/host_vars/` first. Profile names != persona names (Mimir's profile is `mimir-engineer`). For the router's config (Redis URL, password env-var name), follow the same Ansible-templated pattern OR define plugin-local env vars in `requires_env:` of `plugin.yaml`.

**Refs.** home-lab journal entry: `DECISIONS.md 2026-05-25 § "Mimir Hermes profile: engineering council in Asgard, Edge TTS, own voice channel"`. SOUL.md location at `roles/hermes/files/souls/mimir.md`.

---

### Hermes plugin install mechanism  {#hermes-plugin-install}

**Context.** How does code get from `~/workspace/infiquetra/hermes-claude-code-router/` to a running Hermes instance?

**Evidence.** Pattern from `~/workspace/infiquetra/infiquetra-hermes-plugins/scripts/install.sh`. The hermes-claude-code-router repo has a `scripts/` directory that needs the same install.sh copied over (current state: scripts dir exists, install.sh not yet populated as of 2026-05-26).

**Flow:**
1. `./scripts/install.sh plugin hermes_claude_code_router` (or whatever the canonical invocation is)
2. Copies/symlinks `plugins/hermes_claude_code_router/` into `~/.hermes/plugins/hermes_claude_code_router/`
3. If `requirements.txt` exists in the plugin dir, pip-installs into Hermes's shared venv
4. Restart Hermes (or hot-reload via supervisor) to pick up the new plugin

**For production (Mac mini):** rsync or git pull on the target server's home, then run install.sh. NOT directly via Ansible — Ansible doesn't manage individual plugin installs today (the plugin manifest is per-host; plugin payloads are user-installed).

**Generalizable rule.** Plugin development cycle: edit locally → `./scripts/install.sh plugin <name>` to copy to `~/.hermes/plugins/` → restart Hermes. For remote (Mac mini) deploys: `git pull && ./scripts/install.sh plugin <name>` on the server. No Ansible orchestration needed.

**Refs.** [DECISIONS#install-via-scripts-install-sh](DECISIONS.md#install-via-scripts-install-sh). Hermes runs on a server, not the dev laptop — `~/.hermes/` on the laptop has no `plugins/` dir today (verified 2026-05-26).

---

### Hermes plugin manifest (`plugin.yaml`) fields  {#hermes-plugin-manifest}

**Context.** What fields does Hermes actually read from `plugin.yaml` at load time?

**Evidence.** Current router scaffold's `plugins/hermes_claude_code_router/plugin.yaml`:
```yaml
name: hermes-claude-code-router
version: "0.1.0"
description: >-
  Routes Discord text/voice messages to live Claude Code sessions via the
  redis-channel protocol.
provides_hooks:
  - pre_gateway_dispatch
provides_tools:
  - list_cc_sessions
  - set_routing_target
  - get_routing_target
requires_env:
  - name: REDIS_URL
    description: Redis URL...
  - name: REDIS_PASSWORD
    description: Optional password...
```

Per the plugin-authoring docs:
- `name`, `version`, `description` — required
- `requires_env` — Hermes checks at startup; refuses to load if env vars absent
- `provides_hooks`, `provides_tools` — **informational only** (for `hermes plugins list` output); actual registration happens in `register(ctx)`

**Generalizable rule.** The manifest is metadata + load-time env checks; behavior is in `register(ctx)`. Don't expect `provides_hooks` to auto-wire — you still write `ctx.register_hook(...)` in code.

**Refs.** [#hermes-register-ctx-surface](#hermes-register-ctx-surface) for the runtime registration API.

---

### Cross-repo learnings the router build depends on (from `infiquetra-claude-plugins`)

These are stable findings in the **redis-channel plugin's** journal that the router build must respect. Link, don't re-summarize (the source of truth lives there + updates propagate).

- **Channel notifications don't survive `--bg` / `/bg` dispatch.** Channel-capability flags aren't in Claude Code's bg-carry-through set. Router's Phase 5 spawn primitive must use `tmux`-foreground, not `--bg`. → [infiquetra-claude-plugins LEARNINGS#cc-channels-bg-not-supported](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md)
- **Claude Code Channels split terminal + channel surfaces by design.** Don't try to make Claude's local-terminal text mirror the channel reply. The channel user sees the reply via the `reply` tool; the local-terminal user sees "Called plugin:..." collapsed. Documented protocol limitation, not a bug. → [infiquetra-claude-plugins LEARNINGS#cc-channels-surface-split](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md)
- **Plugin runtime coaching belongs in MCP server `instructions=` field, NOT `agents/*.md`.** Subagent definitions aren't auto-loaded into context. Lesson for the router: if you want Claude/Mimir to follow specific coaching, put it where Claude will actually read it. → [infiquetra-claude-plugins LEARNINGS#cc-channels-surface-split](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md)

---

### redis-channel contract surface (the router consumes this)  {#redis-channel-contract}

**Context.** Router talks to the CC-side via Redis Streams. The contract is fully documented in `redis-channel`'s PROTOCOL.md. This entry summarizes what the router needs to know without re-quoting the spec.

**Canonical files** (read these before writing the router's `redis_client.py`):
- [`infiquetra-claude-plugins/plugins/redis-channel/PROTOCOL.md`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/PROTOCOL.md) — wire format
- [`infiquetra-claude-plugins/plugins/redis-channel/server/protocol.py`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/server/protocol.py) — Pydantic models (router should keep its protocol.py byte-identical)
- [`infiquetra-claude-plugins/plugins/redis-channel/docs/STATE_MACHINE.md`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/docs/STATE_MACHINE.md) — router-side routing-target state machine

**Key Redis keys (router uses these):**
- `cc-sessions:registry` (hash) — `HGETALL` for known sessions; filter by `EXISTS cc-sessions:hb:<name>`
- `cc-sessions:hb:<name>` (string, EX 60) — heartbeat; router uses for `is-this-session-still-alive` checks
- `cc-sessions:<name>:inbound` (stream) — router XADDs to this when forwarding a message to CC
- `cc-sessions:<name>:outbound` (stream) — router XREADGROUP's this to consume CC's replies (group name: `hermes-router`)
- `cc-sessions:<name>:permission_request` / `cc-sessions:<name>:permission_verdict` (streams) — for Phase 4 permission relay (deferred)
- `cc-sessions:events:<name>` (pub/sub channel) — lifecycle events (registered, unregistered, mode_change)

**Payload shapes** — re-use the same pydantic models from `redis-channel/server/protocol.py`:
- `Inbound`: `{v, router, endpoint, source, chat_id, user_id, username, text, confidence, ts, metadata}` — router constructs this and XADDs
- `Outbound`: `{v, session_name, endpoint, chat_id, text, voice, in_reply_to, ts}` — router parses on XREADGROUP

**CC-side guarantees** (what the router can rely on):
- Auto-connect via `CLAUDE_CHANNEL_AUTO_CONNECT=1` env var works (verified end-to-end as of `redis-channel` v0.4.18+)
- Consumer group created at `id="$"` BEFORE presence publishes — XREADGROUP `>` after presence is safe
- Heartbeat at 10s intervals; presence persists 60s after death

**Generalizable rule.** Don't reinvent the protocol — the redis-channel side IS the spec. Router's `protocol.py` should be a byte-identical copy of redis-channel's. Schema mismatches → fail loud (Pydantic strict-mode validation).

**Refs.** Plan in [`narratives/2026-05-26-router-build-plan.md`](narratives/2026-05-26-router-build-plan.md) Phase 3 covers the actual implementation.
