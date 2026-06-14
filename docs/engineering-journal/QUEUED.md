# Queued — `hermes-claude-code-router`

> **Future-work items by priority with explicit "worth it when" triggers.** When a promising idea surfaces but we don't build it right now, it goes here. Undocumented good ideas decay into forgotten good ideas.
>
> Format (organized by priority section, no date headers — items durable until shipped or rejected):
>
> ```markdown
> ### Short title  {#slug}
>
> **Priority.** P0 (must-ship-before-X) / P1 (urgent) / P2 (important) / P3 (nice-to-have) / Maybe.
> **Effort.** Rough estimate.
> **Worth it when.** Specific trigger.
> **Context.** What surfaced this + cross-refs.
> ```
>
> When a queued item ships, move to [ARCHIVE.md](ARCHIVE.md) as SHIPPED with commit hash. When rejected, move with REJECTED + reason.

---

## P1 — urgent

### Voice transcript routing (Phase 4 in revised plan; was master Phase 3)  {#voice-transcript-routing}

**Priority.** P1 — blocks the original "hands-free CC while driving" promise, but text routing (Phase 3) ships first per [DECISIONS#text-chat-first-milestone](DECISIONS.md#text-chat-first-milestone).

**Effort.** ~2-3 days on top of working text routing.

**Worth it when.** (a) Text routing (Phase 3) has shipped + been used in production for ≥1 week; (b) voice-forge is a first-order Hermes TTS provider OR we accept Edge TTS as a stopgap; (c) the related sub-items [voice-forge HTTP integration](#voice-forge-http-integration) and [Discord voice playback](#discord-voice-playback) are scoped.

**Context.**
- Voice transcripts come through the same `pre_gateway_dispatch` hook with `event.message_type=="voice"` (see [LEARNINGS#voice-via-pre-gateway-dispatch](LEARNINGS.md#voice-via-pre-gateway-dispatch)).
- Once routing logic exists for text, voice differs only in: (a) the toggle phrases ("start coding session" / "end coding session"), (b) outbound `voice=true` triggers TTS+playback instead of channel.send.
- No STT confidence available (see [LEARNINGS#stt-confidence-not-propagated](LEARNINGS.md#stt-confidence-not-propagated)) — accept all transcripts; Claude will ask for clarification if quality is bad.

---

### voice-forge HTTP TTS integration  {#voice-forge-http-integration}

**Priority.** P1 (sub-item of voice transcript routing).

**Effort.** ~half-day. HTTP client to `POST /v1/audio/speech` with text + voice_id; parse WAV response; pass to discord.py audio source.

**Worth it when.** Voice transcript routing work begins.

**Context.**
- voice-forge runs on `jeffs-mac-mini.infiquetra.com:9876` (launchd label `ai.hermes.voice-forge`). Per the home-lab Phase G cutover (LEARNINGS 2026-05-24 in home-lab journal).
- OpenAI-compatible endpoint at `POST /v1/audio/speech`; returns WAV (mono int16 PCM, 24kHz, with WAV headers).
- For Mimir specifically: voice-forge isn't currently used (Mimir is on Edge TTS per [LEARNINGS#mimir-profile-config-location](LEARNINGS.md#mimir-profile-config-location)). Decision pending: do we use voice-forge for the router's TTS even though Mimir's LLM-side uses Edge? OR mirror Mimir's Edge TTS for consistency?
- Edge TTS fallback: shell out to `edge-tts --voice en-GB-RyanNeural --text "<text>" --write-media <file>`. Faster, no HTTP dep, but locked to Microsoft's voice list.
- voice-forge has a known streaming-content-loss issue (NeuTTS streaming drops 15-21% vs batch — see home-lab LEARNINGS 2026-05-24). For the router, use batch synthesis (no streaming) to avoid that gap.

---

### Discord voice playback via `discord.py` voice_client  {#discord-voice-playback}

**Priority.** P1 (sub-item of voice transcript routing).

**Effort.** ~half-day. Reach into `adapter._voice_clients[guild_id]`, construct `discord.FFmpegPCMAudio(audio_bytes)`, call `voice_client.play(...)`. Handle queue serialization (multiple replies back-to-back).

**Worth it when.** voice-forge HTTP integration is ready (or Edge TTS fallback is wired) AND voice transcript routing is in progress.

**Context.**
- Pattern from `asgard_voice_arbiter/__init__.py:294,301` for reaching the voice client.
- No existing Hermes plugin plays TTS audio out-of-band (asgard_voice_arbiter only handles INBOUND voice). We'll be the first.
- discord.py's `voice_client.play()` is fire-and-forget; need to queue subsequent plays manually (overlapping plays would clobber each other).
- Failure modes: (a) Mimir not in voice channel (no voice client); (b) voice channel closed mid-play; (c) FFmpeg pipe fails. Plan for graceful degradation.

---

### AskUserQuestion interception over Discord buttons (Phase 5 in revised plan; partial)  {#askuserquestion-discord-buttons}

**Priority.** P1 (when permission relay is built; Phase 5 of revised plan).

**Effort.** ~1 day. Hook the AskUserQuestion intercept on the CC plugin side; emit a `permission_request`-like stream entry; router consumes + DM's the user with Allow/Deny + multi-choice buttons (discord.py interactions); router XADDs `permission_verdict` back to CC.

**Worth it when.** Text routing (Phase 3) has shipped AND permission relay (Phase 4 voice-side) is in progress. Discord button approval is a useful complement to voice approval — they cover different UX modes (phone with sound on vs. silent at desk).

**Context.**
- Master plan's Phase 4 covers this; the AskUserQuestion intercept itself happens on the CC-plugin side (per [redis-channel PROTOCOL.md](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/PROTOCOL.md) "AskUserQuestion interception" section + master plan's design).
- Discord buttons reference pattern: `claude-plugins-official/discord` plugin uses Allow/Deny buttons in ephemeral DMs for tool permissions (see `server.ts:486-518`). Mirror that shape.

---

## P2 — important

### Outbound relay PEL auto-reclaim (at-least-once redelivery)  {#outbound-pel-reclaim}

**Priority.** P2.

**Effort.** ~half-day. Add an `XAUTOCLAIM` (or `id="0"` PEL re-read) pass to `OutboundRelay.poll_once` with a min-idle-time, a retry cap, and a dead-letter / give-up path.

**Worth it when.** v1 text routing is in real use AND a transient Discord failure (rate-limit, network blip, gateway-not-yet-captured) is observed stranding a reply in the PEL — or before relying on at-least-once delivery semantics.

**Context.** The v1 code-review fix (commit `abc0c12`) stopped ACKing failed deliveries (no more silent loss — a P2 was that failed sends were ACKed-and-lost), but `poll_once` reads with `>` only, so a pending entry is **not auto-redelivered**; it waits for a manual claim / restart. Surfaced by the v1 code-review re-verification. Needs a retry-cap + dead-letter so a permanently-failing send can't accumulate unbounded PEL entries. See `plugins/hermes_claude_code_router/outbound.py` (`_default_send` / `poll_once`).

### Phase 5 spawn primitive depends on `claude-channel --tmux` flag (infiquetra-claude-plugins)  {#phase5-spawn-via-tmux}

**Priority.** P2 — blocks Phase 5 (Mimir's `start_cc_session` LLM tool).

**Effort.** Zero in THIS repo (the implementation lives in infiquetra-claude-plugins/redis-channel's `claude-channel.sh`). Trigger: file an issue / PR over there when Phase 5 work needs it.

**Worth it when.** Implementing Phase 5's `start_cc_session` LLM tool, which is "Mimir asks Claude to spawn a CC session for me."

**Context.**
- Background-dispatched claude sessions (`claude --bg`, `/bg`) silently drop channel notifications — see [`infiquetra-claude-plugins LEARNINGS#cc-channels-bg-not-supported`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md#cc-channels-bg-not-supported).
- Workaround: spawn in a detached tmux session that runs claude in the foreground (claude has the dev-channels flag in argv; channels work).
- The QUEUED entry over there: [`infiquetra-claude-plugins QUEUED#phase5-spawn-via-tmux`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/QUEUED.md#phase5-spawn-via-tmux) describes adding `--tmux` mode to `claude-channel`.
- From this side (router): when Phase 5 work begins, the LLM tool `start_cc_session(cwd, name)` shells out to `claude-channel --tmux --session-name <name> --cwd <cwd>` (or whatever final API the wrapper exposes), polls `EXISTS cc-sessions:hb:<name>` for readiness, returns session metadata.

---

### Permission relay voice path (Phase 4-voice in revised plan)  {#permission-relay-voice-deferred}

**Priority.** P2.

**Effort.** ~1 day in the router + ~half-day on the CC plugin side.

**Worth it when.** Voice transcript routing (Phase 4-text) is working AND we've decided the destructive-action UX (echo-confirm? 30s window? confidence floor?).

**Context.**
- Master plan's Phase 4 design: voice prompt via TTS ("Bash command needs approval, say yes <id> or no <id> within 30s"), STT yes/no listener with destructive echo-confirm.
- Confidence floor is unworkable (per [LEARNINGS#stt-confidence-not-propagated](LEARNINGS.md#stt-confidence-not-propagated)) — degrade to "accept any matched phrase".
- Pairs with [#askuserquestion-discord-buttons](#askuserquestion-discord-buttons) for the silent / desk UX.
- Audit log: master plan §4.8 specifies JSONL fields. Implement on the router side at `~/.hermes/plugins/hermes_claude_code_router/audit.jsonl`.

---

### Hybrid LLM tool dispatch (Phase 5 router-side; was master Phase 5)  {#hybrid-llm-tool-dispatch}

**Priority.** P2.

**Effort.** ~1 day. Register `list_cc_sessions`, `set_routing_target`, `get_routing_target` as Mimir-visible LLM tools via `ctx.register_tool(...)`. Wire system-prompt mention. Add routing-logic fallback: if regex/slash matches → act; else if message has session-intent keywords (`session`, `claude code`, `connect`, `switch`, etc.) AND no target set → hand to Mimir LLM with tools.

**Worth it when.** Text routing (Phase 3) is shipped + has been used for a few days. We'll know the regex/slash matchers' false-negative rate and the LLM-fallback can fill the gap.

**Context.**
- Master plan §5 covers this.
- Tools take a session_name + optionally a cwd / git_branch as input; return ok/error + new routing target.
- Mimir LLM's tool-use protocol (Claude tool-use) means schema is JSON Schema.
- Risk: LLM-fallback adds 2-4s latency over regex/slash. Document this; users who want fast should learn the slash pattern.

---

## P3 — nice-to-have

### Anchor config-supplied matcher patterns  {#anchor-config-matcher-patterns}

**Priority.** P3.

**Effort.** ~1-2h. In `matchers._compile`, prepend `^\s*` to a config-supplied pattern that doesn't already start with `^` (or validate + warn at compile time); fix the unanchored example in `docs/STATE_MACHINE.md`.

**Worth it when.** Per-profile `connect_patterns` / `switch_patterns` host_vars are actually wired. Today only the anchored built-in defaults are used, so production is safe.

**Context.** v1 anchored the DEFAULT control patterns (fixing the mid-sentence-hijack P1), but `_compile` compiles operator-supplied patterns verbatim — an unanchored config pattern re-introduces the hijack, and the STATE_MACHINE.md example pattern is itself unanchored. Surfaced by the v1 code-review re-verification. See `plugins/hermes_claude_code_router/matchers.py` (`_compile`).

### Multi-conversation routing target scoping  {#multi-conversation-routing-target-scoping}

**Priority.** P3.

**Effort.** ~half-day if we keep state in plugin memory; ~1 day if we move to Redis-backed state.

**Worth it when.** Multiple Mimir users concurrently use the router (today: single-user only). OR a single user reports confusing routing behavior across DM vs. channel vs. thread surfaces.

**Context.**
- Master plan calls for routing target keyed by `(user_id, profile, chat_id)`. Today's design: one routing target per Mimir conversation = `(user_id, mimir, channel_or_thread_id)`. Suffices for solo use.
- If a second user starts using Mimir-routed CC, the keying becomes load-bearing.
- See [DECISIONS#routing-target-in-plugin-memory](DECISIONS.md#routing-target-in-plugin-memory).

---

### Proactive notifications ("session X is waiting on approval")  {#proactive-notifications}

**Priority.** P3 (master plan v2 candidate).

**Effort.** ~half-day. Subscribe to `cc-sessions:events:<name>` pubsub on the router side; when a `permission_request` lifecycle event arrives, DM the user proactively rather than waiting for them to query.

**Worth it when.** Permission relay (Phase 4) has shipped + been in use for a few weeks. We'll know which "waiting on me" events are useful to push vs. noisy.

**Context.** Master plan §"Out of scope (v1)" mentioned proactive notifications as v2.

---

### Session-mode awareness from Discord (e.g., voice-toggle plan mode)  {#session-mode-awareness}

**Priority.** Maybe (master plan calls this "Out of scope, period").

**Effort.** Unknown — requires Claude Code to surface session mode via the channel protocol.

**Worth it when.** Claude Code adds session-mode introspection to the channel protocol. Until then, can't do.

**Context.** Master plan §Out of scope explicitly: "Session-mode awareness or toggling from Discord — protocol can't, period."

---

### Cross-WAN access (Tailscale)  {#cross-wan-tailscale}

**Priority.** Maybe (master plan v2 candidate).

**Effort.** ~1 day, orthogonal to router code (network config).

**Worth it when.** User wants to drive a CC session from outside their LAN. Today: phone is on home wifi or VPN'd in.

**Context.** Master plan §Out of scope calls this "would add Tailscale; orthogonal."

---

### Telegram / iMessage / SMS surface bridges  {#alt-surface-bridges}

**Priority.** Maybe.

**Effort.** Each is ~1-2 days. Separate Hermes plugins (sibling repos to hermes-claude-code-router).

**Worth it when.** Discord-via-Hermes is working AND user wants a non-Discord surface (e.g., Telegram for travel where Discord is blocked).

**Context.** Master plan §Out of scope: "Telegram/iMessage/SMS bridges (same `redis-channel` could in principle be used by an analogous Telegram-Hermes plugin)." The redis-channel side is already router-agnostic.

---

### Stress-test multi-session routing in v1  {#stress-test-multi-session}

**Priority.** Maybe.

**Effort.** ~half-day. Spin up 3+ CC sessions, route Mimir messages across them, observe state machine + heartbeat behavior under load.

**Worth it when.** v1 has shipped end-to-end and user reports a multi-session bug. Per master plan §"Multi-session in v1": "Infrastructure: yes... Stress-test with N: no, iterate with 1."

**Context.** The redis-channel side handles multi-session correctly (registry indexes by name). The router's stress is in routing-state mgmt + UX for "list sessions" with 5+ rows.
