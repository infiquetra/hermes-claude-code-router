# Engineering journal — `hermes-claude-code-router`

This directory IS the engineering journal. The files inside are its sections.

| File | Purpose |
|------|---------|
| [LEARNINGS.md](LEARNINGS.md) | Empirical findings + mechanisms + fixes + validations |
| [DECISIONS.md](DECISIONS.md) | ADR-style records of plugin-pattern / convention / tooling choices |
| [QUEUED.md](QUEUED.md) | Future-work items by priority with "worth it when" triggers |
| [ARCHIVE.md](ARCHIVE.md) | Shipped + rejected + superseded items |
| [narratives/](narratives/) | Self-contained, longer-form companion docs (plan walkthroughs, multi-PR post-mortems) |

## Maintenance rules (Claude: follow without being asked)

1. **After fixing a bug or shipping a feature where the mechanism wasn't obvious** → add a dated entry to `LEARNINGS.md`. Include **evidence** (PR/commit/file:line) and **mechanism** (why it happened, not just what), and a **Generalizable rule** line.

2. **After committing a pattern/convention decision** → add to `DECISIONS.md` with rationale + rejected alternatives + "revisit when" condition.

3. **Whenever a promising idea surfaces but we don't build it right now** → `QUEUED.md` with P0/P1/P2/P3/Maybe, a "worth it when" trigger, rough effort.

4. **When a QUEUED item ships** → move to `ARCHIVE.md` as SHIPPED with commit hash + date.

5. **When a QUEUED item is rejected** → move to `ARCHIVE.md` as REJECTED with reason + revisit conditions.

6. **When a prior entry is invalidated** → update inline AND move pre-correction version to `ARCHIVE.md` as SUPERSEDED. Never silently overwrite.

7. **When something needs a longer write-up** → create `narratives/YYYY-MM-DD-short-slug.md` and link from the relevant LEARNINGS / DECISIONS entry.

Entry format. Each of the four core files has a block-quote intro at the top spelling out its format. Use subheaders where applicable: **Context / Evidence / Mechanism / Fix (or queued) / Validation / What surprised / Generalizable rule / Refs**. The **Generalizable rule** line is the highest-value field.

**Don't wait to be asked.** When any of these triggers fire, update the files as part of the same commit.

## Quick navigation by topic

- The whole router build plan (text-first, voice deferred) → [narratives/2026-05-26-router-build-plan.md](narratives/2026-05-26-router-build-plan.md)
- Why voice routing is deferred until voice-forge is a first-order Hermes provider → [DECISIONS](DECISIONS.md#voice-deferred-until-voice-forge-first-order)
- Why text-chat (Discord DM/channel) is the router's first milestone → [DECISIONS](DECISIONS.md#text-chat-first-milestone)
- `pre_gateway_dispatch` hook contract (verified against asgard_voice_arbiter) → [LEARNINGS](LEARNINGS.md#hermes-pre-gateway-dispatch-contract)
- Hermes plugin `register(ctx)` API surface → [LEARNINGS](LEARNINGS.md#hermes-register-ctx-surface)
- Voice transcripts come through the same `pre_gateway_dispatch` hook (not a separate one) → [LEARNINGS](LEARNINGS.md#voice-via-pre-gateway-dispatch)
- No `gateway.send_message()` API; use `adapter._client.get_channel(id).send(text)` for outbound text → [LEARNINGS](LEARNINGS.md#outbound-text-via-discord-py)
- For plugin out-of-band voice: synth ourselves via voice-forge HTTP + play via discord.py voice_client → [LEARNINGS](LEARNINGS.md#out-of-band-voice-pattern)
- STT confidence not propagated to plugin hooks → [LEARNINGS](LEARNINGS.md#stt-confidence-not-propagated)
- Channel notifications don't survive `--bg` / `/bg` (cross-repo) → cross-link to [infiquetra-claude-plugins LEARNINGS#cc-channels-bg-not-supported](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/LEARNINGS.md)
- Mimir profile config location → [LEARNINGS](LEARNINGS.md#mimir-profile-config-location)
- Phase 5 spawn primitive: tmux-wrapped foreground (depends on infiquetra-claude-plugins#phase5-spawn-via-tmux) → [QUEUED](QUEUED.md#phase5-spawn-via-tmux)
- voice-forge HTTP TTS integration → [QUEUED](QUEUED.md#voice-forge-http-integration)
- Discord voice playback via discord.py voice_client → [QUEUED](QUEUED.md#discord-voice-playback)
- AskUserQuestion interception via Discord buttons → [QUEUED](QUEUED.md#askuserquestion-discord-buttons)
- File feature request for channels-in-bg → cross-link to [infiquetra-claude-plugins QUEUED#channels-in-bg-feature-request](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/docs/engineering-journal/QUEUED.md)
