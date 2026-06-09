# Router build plan (revised 2026-05-26)

> **Context.** This is a REVISED version of `~/.claude/plans/i-would-like-to-distributed-hanrahan.md` (master plan), scoped specifically to the router-side build in this repo. Re-scoped after the redis-channel build (companion repo `infiquetra/infiquetra-claude-plugins`) finished its CC-plugin-side phases through v0.5.0 (PRs #128-153) and surfaced learnings that change Phase 3+ design.
>
> **Read this file as a starting point for the next router-implementation session.** It's NOT a final approved plan — it should be re-reviewed + finalized via plan mode at the start of that session. The master plan stays at `~/.claude/plans/i-would-like-to-distributed-hanrahan.md` as a historical artifact.

## What changed since the master plan

| Master plan assumption | Revised reality |
|---|---|
| Phase 3 = voice routing (Hermes TTS/STT integration) | Phase 3 = **text routing only** (Discord DM + channel mention + thread). Voice deferred to Phase 4. |
| Phase 5 spawn uses `claude --bg` | Phase 5 spawn uses **tmux-wrapped foreground** (`--bg` drops channel notifications — see [LEARNINGS#cc-channels-bg-not-supported in companion repo](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md)) |
| Hermes auto-TTSes plugin replies based on originating-event context | Only for Mimir-LLM-driven responses. Plugin out-of-band sends bypass auto-TTS — see [LEARNINGS#out-of-band-voice-pattern](../LEARNINGS.md#out-of-band-voice-pattern). |
| Voice transcript has its own hook | Voice + text both come through `pre_gateway_dispatch`; distinguish by `event.message_type` — see [LEARNINGS#voice-via-pre-gateway-dispatch](../LEARNINGS.md#voice-via-pre-gateway-dispatch). |
| STT confidence is available | It isn't — see [LEARNINGS#stt-confidence-not-propagated](../LEARNINGS.md#stt-confidence-not-propagated). Master plan's confidence-threshold voice approval is unworkable as written. |
| Mimir profile at `~/.hermes/profiles/mimir/` | It's `mimir-engineer` (Ansible-templated), config at `home-lab/ansible/inventory/host_vars/jeffs-mac-mini.infiquetra.com.yml`. Mimir uses **Edge TTS**, NOT voice-forge. — see [LEARNINGS#mimir-profile-config-location](../LEARNINGS.md#mimir-profile-config-location). |

## Current state of THIS repo (as of 2026-05-26)

- **Initial scaffold only** (commit `e89f0d2`). One commit on `main`.
- `plugins/hermes_claude_code_router/` has: `__init__.py` with stub `register(ctx)`, `plugin.yaml`, `protocol.py` (Pydantic models matching `redis-channel/server/protocol.py`), `PROTOCOL.md` (canonical wire format, byte-identical to `redis-channel`'s), empty `tests/`, `requirements.txt`.
- No `router.py`, `matchers.py`, `mode_state.py`, `redis_client.py`, `permission.py`, `llm_tools.py`, `registry_reader.py` yet.
- `scripts/` exists but `install.sh` not yet populated (needs adaptation from `infiquetra-hermes-plugins/scripts/install.sh`).

## Phased build (revised)

### Phase 1 (router-side) — Presence reader + `/cc list` slash

**Goal.** The router can answer "what CC sessions are live?" via slash command and voice query.

1. `plugins/hermes_claude_code_router/registry_reader.py` — connect to Redis (URL + password env from `requires_env`); `HGETALL cc-sessions:registry`; filter by `EXISTS cc-sessions:hb:<name>`; return list of session metadata dicts.
2. `plugins/hermes_claude_code_router/redis_client.py` — Redis connection helper with URL-encoded password (see `infiquetra-claude-plugins/plugins/redis-channel/server/redis_client.py` for the canonical pattern; mirror it).
3. `plugins/hermes_claude_code_router/__init__.py` — `register(ctx)` registers a slash command `/cc list` and a voice-pattern matcher for "list sessions" / "list cc sessions" / "what sessions are live".
4. Output formatting: Discord embed or plain message with session name, cwd-basename, git_branch, started-at, last-seen-seconds-ago.
5. **Verify.** From this side: start 2 CC sessions (foreground claude-channel) on the dev laptop pointing at the user's Redis; from Discord, "/cc list" enumerates both. Kill one; within 60s it drops off.

**Estimated effort.** 1-1.5 days.

### Phase 2 (router-side) — Routing-target state + slash matchers + suppress Mimir LLM

**Goal.** When user says "connect to session foo" or "/cc connect foo" in Discord, the router stores `(user_id, mimir, chat_id) → "foo"` and returns `{"action": "skip"}` from `pre_gateway_dispatch` to prevent Mimir's LLM from responding to subsequent messages.

1. `plugins/hermes_claude_code_router/mode_state.py` — in-memory dict per `(user_id, profile, chat_id)`; functions: `set_target(key, session_name)`, `clear_target(key)`, `get_target(key)`.
2. `plugins/hermes_claude_code_router/matchers.py` — regex patterns for connect/disconnect/list/switch + mode toggle (`start coding session`, `end coding session`). Configurable via `plugin.yaml` to support per-profile customization (matches master plan §Configuration).
3. `plugins/hermes_claude_code_router/router.py` — the `pre_gateway_dispatch` handler. Match against patterns first; if match, mutate `mode_state` + return `{"action": "skip", "reason": "router consumed"}`. If no match + target set + message is text → fall through to Phase 3 (XADD to inbound). If no target → return `None` (let Mimir's LLM respond).
4. **Verify.** From Discord DM Mimir, "connect to session foo" → Mimir doesn't respond (skipped). "list sessions" → shows the routing target. "disconnect" → routing target cleared; subsequent DMs go back to Mimir LLM.

**Estimated effort.** 1.5-2 days.

### Phase 3 (router-side) — Text bridge (Discord DM + channel mention + thread)

**Goal.** With routing target set, user-DM → CC session → reply → back to user's Discord.

1. `plugins/hermes_claude_code_router/redis_client.py` — XADD inbound + XREADGROUP outbound (group name: `hermes-router`); validate payloads against `protocol.py` Pydantic models.
2. Extend `router.py`'s `pre_gateway_dispatch`: when target is set + message is text, construct `Inbound` payload from the event (chat_id derived from Discord channel/DM/thread ID), XADD to `cc-sessions:<target>:inbound`, return `{"action": "skip"}`.
3. Background asyncio task (started in `register(ctx)` — uses `asyncio.create_task` on `ctx`'s loop OR a thread per session-target) consumes outbound: `XREADGROUP GROUP hermes-router consumer-1 BLOCK 1000 STREAMS cc-sessions:<target>:outbound >`. For each message:
   - Parse as `Outbound`
   - Reach into `adapter._client.get_channel(chat_id).send(text)` via `asyncio.run_coroutine_threadsafe` (see [LEARNINGS#outbound-text-via-discord-py](../LEARNINGS.md#outbound-text-via-discord-py))
   - If `in_reply_to` is set, use `discord.py`'s reply-to-message feature (`channel.send(text, reference=msg)` if msg can be fetched)
4. Text surface coverage: DM, guild channel @mention, thread reply. The hook's `event.message_type` may differ for these (`"text"`, `"mention"`, `"thread"`?) — verify against the actual event shape during build.
5. **Verify (end-to-end).**
   - User opens a foreground claude-channel session locally: `claude-channel --session-name dev-test`. CC plugin auto-connects to mimir endpoint.
   - User DMs Mimir on Discord: "connect to session dev-test"
   - User DMs Mimir: "what's the status of PR #117?" → routes to dev-test CC session, Claude replies, reply appears as Mimir's DM response
   - User DMs Mimir: "disconnect" → router clears target; next DM goes to Mimir LLM normally

**Estimated effort.** 2-2.5 days.

**At this point, the router is functionally useful** — Discord text + CC = hands-on-keyboard workflow without sitting at a terminal. Voice is a separate phase on top.

### Phase 4 (router-side) — Voice transcript routing

**Deferred per [DECISIONS#voice-deferred-until-voice-forge-first-order](../DECISIONS.md#voice-deferred-until-voice-forge-first-order).** When Phase 3 is shipped + working AND voice-forge is a first-order Hermes TTS provider, come back and:

1. Extend the `pre_gateway_dispatch` handler to also handle `event.message_type=="voice"`. Same matcher logic + state transitions as text.
2. For outbound `voice=true` payloads: synth via voice-forge HTTP `POST /v1/audio/speech` (or Edge TTS subprocess if we decide that) → bytes → `discord.FFmpegPCMAudio` → `voice_client.play(...)` in the originating voice channel.
3. Handle TTS queue serialization (back-to-back replies must not clobber each other on the voice_client).
4. Permission-relay voice path: master plan §4 design (TTS prompt + STT yes/no listener + 30s window + destructive echo-confirm). Audit log to `~/.hermes/plugins/hermes_claude_code_router/audit.jsonl`.

See [QUEUED#voice-transcript-routing](../QUEUED.md#voice-transcript-routing) + sub-items.

**Estimated effort.** 2-3 days when triggered.

### Phase 5 (router-side) — Hybrid LLM tool dispatch + programmatic session spawn

**Goal.** Mimir's LLM can call `list_cc_sessions`, `set_routing_target`, `get_routing_target` to handle natural-language requests ("let me pick up the auth feature work" → LLM finds the session by branch/cwd and sets target). Plus: `start_cc_session(cwd, name)` to spawn a new CC session on demand.

1. `plugins/hermes_claude_code_router/llm_tools.py` — JSON Schema definitions + handlers for the three tools. Register via `ctx.register_tool(name, schema, handler)` (see [LEARNINGS#hermes-register-ctx-surface](../LEARNINGS.md#hermes-register-ctx-surface)).
2. Routing logic update in `router.py`: if regex/slash match → act directly (no LLM call). Else if message has session-intent keywords (`session`, `claude code`, `connect`, `switch`, `work on`, `yesterday`, `feature`, `branch`) AND no target set → hand to Mimir LLM with tools. LLM decides whether to call a tool or respond normally.
3. **`start_cc_session(cwd, name)` tool** — shells out to `claude-channel --tmux --session-name <name> --cwd <cwd>` (depends on companion repo work: see [QUEUED#phase5-spawn-via-tmux](../QUEUED.md#phase5-spawn-via-tmux)). Polls `EXISTS cc-sessions:hb:<name>` until live. Returns metadata.
4. Update Mimir's system prompt (via host_vars) to mention the new tools.
5. **Verify.** Voice or text: "let's pick up the auth feature work I was doing earlier" → Mimir LLM calls `list_cc_sessions`, infers from `git_branch` + `cwd`, calls `set_routing_target("auth-feature-abc123")`. Confirm verbally; user proceeds.

See [QUEUED#hybrid-llm-tool-dispatch](../QUEUED.md#hybrid-llm-tool-dispatch).

**Estimated effort.** 1.5-2 days (excludes voice — assumes voice has shipped in Phase 4).

### Phase 6 (router-side) — Polish + multi-profile + docs

1. README.md + CHANGELOG.md + ARCHITECTURE.md (router-side).
2. `scripts/install.sh` polished + tested fresh-install.
3. Multi-profile support: per-Hermes-profile config of mode_phrases / connect_patterns / list_patterns (master plan §Configuration shows the yaml structure).
4. Optional: `/cc configure` slash command for runtime adjustments.
5. **Verify.** Clean install on a fresh Mac mini (or wherever Hermes runs); driving sim end-to-end through text first, then voice.

**Estimated effort.** 1-2 days.

## Total effort estimate

- Phase 1: 1-1.5 days
- Phase 2: 1.5-2 days
- Phase 3: 2-2.5 days  ← **stop here for v1; voice deferred**
- (Phase 4: 2-3 days — when triggered)
- (Phase 5: 1.5-2 days — when triggered)
- (Phase 6: 1-2 days — when triggered)

**v1 router (Phases 1-3): ~5 days.** Phases 4-6 layer on top across subsequent weeks.

## Critical reference paths

When the next session starts, READ THESE FIRST:

- This file (you're reading it).
- [LEARNINGS.md](../LEARNINGS.md) — every entry. Especially `#hermes-register-ctx-surface`, `#hermes-pre-gateway-dispatch-contract`, `#outbound-text-via-discord-py`, `#redis-channel-contract`.
- [DECISIONS.md](../DECISIONS.md) — the rationale-of-record for the re-scoping.
- [QUEUED.md](../QUEUED.md) — what's deferred + when to revisit.
- Master plan: `~/.claude/plans/i-would-like-to-distributed-hanrahan.md` — historical artifact + still-load-bearing for Phases 4-6 design intent.
- Companion repo: [`infiquetra/infiquetra-claude-plugins`](https://github.com/infiquetra/infiquetra-claude-plugins) — specifically `plugins/redis-channel/PROTOCOL.md`, `protocol.py`, `docs/STATE_MACHINE.md`, and that repo's `docs/engineering-journal/LEARNINGS.md` (especially `#cc-channels-bg-not-supported` and `#cc-channels-surface-split`).
- Reference Hermes plugins: `~/workspace/infiquetra/infiquetra-hermes-plugins/plugins/security_guidance/` (simplest example), `~/workspace/infiquetra/home-lab/ansible/roles/hermes/files/plugins/asgard_voice_arbiter/__init__.py` (real `pre_gateway_dispatch` patterns).
- Hermes deployed profile config: `~/workspace/infiquetra/home-lab/ansible/inventory/host_vars/jeffs-mac-mini.infiquetra.com.yml` (mimir-engineer).
- voice-forge: `~/workspace/infiquetra/voice-forge/src/voice_forge/` (HTTP API for Phase 4).

## How to start the next session

1. Open Claude Code in `~/workspace/infiquetra/hermes-claude-code-router`.
2. Reference this file early in the conversation.
3. Enter plan mode if the user wants to finalize the implementation plan before executing.
4. Start with Phase 1 (presence reader + `/cc list` slash) — smallest, most contained piece.
5. Each phase ends with a verify step that requires real Discord + Mimir interaction; plan for that being slower than CC-plugin-side dev (where I could XADD test messages with Python scripts).
