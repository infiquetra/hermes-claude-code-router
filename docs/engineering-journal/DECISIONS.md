# Decisions — `hermes-claude-code-router`

> **ADR-style records of plugin-pattern / convention / tooling choices.** Each decision captures the **rationale**, **rejected alternatives**, and **"revisit when"** condition so future-us knows what assumptions could change. Include commit hash where applicable.
>
> Format:
>
> ```markdown
> ## YYYY-MM-DD
>
> ### Short title (commit-hash)  {#slug}
>
> **Decision.** What was decided.
> **Rationale.** Why.
> **Rejected alternatives.** What else we considered + why it lost.
> **Revisit when.** Conditions that would make us reopen this.
> **Refs.** Cross-links.
> ```

---

## 2026-06-14

### Direction expanded: autonomous operation is a co-equal destination (STRATEGY.md first run)  {#dual-operator-autonomy-co-equal}

**Decision.** The project's committed direction expands from human-in-the-loop relay only to **two co-equal destinations**: (1) **human-proxied operation** — you talk to the Hermes operator agent (Mimir), it relays/switches/orchestrates your live Claude Code sessions; and (2) **autonomous operation** — Mimir coordinates sessions toward a goal handed to it once, with no human in the loop. "Coordinate toward a goal" is the success-definer; fire-and-check and supervise-and-approve are the rungs below it. Recorded in [`STRATEGY.md`](../../STRATEGY.md).

**Rationale.** The master plan and this journal scoped the router as a human-in-the-loop relay ("user picks one or none per conversation"). During the `/strategy` interview Jeff named autonomous agent operation as an *equally-desired* destination, not a v2 afterthought. Treating both as co-equal lets them share one substrate — the same tools/streams an autonomous Mimir calls are the ones a human-proxied Mimir calls — instead of forking into two products. Two structural consequences follow and are now load-bearing:
- **Voice / operator-interface is fully upstream.** The connector only ever sees formatted text against a predetermined contract; how the operator was reached (voice, typed, Discord) is the agent's job, not this repo's. The connector's identity is the *operator↔session control plane*, not a chat/voice bridge.
- **Permission / safety / audit moves from deferred to foundational.** An agent self-approving `Bash`/`Write` in real repos needs the approval + audit spine built *before* unsupervised operation, not after text routing ships.

**Rejected alternatives.**
- *Keep human-relay-only; treat autonomy as out-of-scope v2.* Rejected: Jeff explicitly wants autonomy as a co-equal destination, and designing the control plane without a non-human operator in mind risks a surface only a human can drive.
- *Make autonomy the sole north star; treat human-relay as scaffolding.* Rejected: Jeff wants both as real destinations, neither subordinate.

**Revisit when.** Autonomy design exploration (next: `/ideate` or `/brainstorm`) shows that goal-coordination belongs in the agent rather than the connector, OR that no acceptable safety model exists for unsupervised self-approval — either would re-scope the "Autonomy & safety" track.

**Refs.** [`STRATEGY.md`](../../STRATEGY.md). Puts these prior decisions in tension pending reconciliation during re-plan (do NOT treat as superseded yet — the re-plan owns that): [#permission-relay-deferred](#permission-relay-deferred) (relay was deferred to Phase 5; now foundational), [#voice-deferred-until-voice-forge-first-order](#voice-deferred-until-voice-forge-first-order) + [#text-chat-first-milestone](#text-chat-first-milestone) (voice was deferred-in-repo; now upstream-out-of-repo). Build plan needing reconciliation: [`narratives/2026-05-26-router-build-plan.md`](narratives/2026-05-26-router-build-plan.md).

## 2026-06-09

### Point router guidance at the renamed Hermes plugin repo (commit `4c8fcfb`)  {#renamed-hermes-plugin-repo-guidance}

**Decision.** Use `infiquetra-hermes-plugins` as the canonical pattern/source repository in router
README, agent guidance, changelog, journal guidance, narrative planning notes, and plugin docstrings.

**Rationale.** This router was scaffolded from the Hermes-facing plugin repository. After the
repository rename, current guidance should point at the canonical name so future plugin work copies
from the maintained source rather than from a redirect.

**Rejected alternatives.**
- *Rely on GitHub redirects.* Rejected: redirects keep links working but do not teach agents the
  canonical repository name.
- *Only update README links.* Rejected: AGENTS and journal entries are the surfaces agents actually
  use while implementing follow-up router work.

**Revisit when.** The router becomes independent of the Hermes plugin repo layout, or the plugin
authoring source moves into upstream Hermes documentation.

**Refs.** `AGENTS.md`; `README.md`; `docs/engineering-journal/LEARNINGS.md`.

## 2026-05-26

### Agent guidance entrypoints symlink to AGENTS.md  {#agent-guidance-symlinks-to-agents-md}

**Decision.** `AGENTS.md` is the canonical repo guidance file for agentic coding CLIs. `CLAUDE.md`, `CODEX.md`, `GEMINI.md`, and `ANTIGRAVITY.md` are committed relative symlinks to `AGENTS.md`.

**Rationale.** Multiple CLIs need the same repo-specific context, but copied Markdown files drift. Git preserves symlink entries, GitHub displays them, and macOS/Linux clones recreate them. A single canonical file keeps behavior independent of which supported tool edits the guidance.

**Rejected alternatives.**
- *Generated copies from a template.* Rejected: adds script and workflow complexity for no current benefit.
- *Thin wrapper files that tell each tool to read `AGENTS.md`.* Rejected: lower confidence because it depends on each tool following the wrapper instruction.
- *Keep only `CLAUDE.md`.* Rejected: Codex, Gemini, and Antigravity may not load Claude-specific filenames.

**Revisit when.** A supported target environment cannot use committed symlinks, or one of the CLIs standardizes on a different universal guidance filename with broad support.

**Refs.** Root `AGENTS.md`; sync guard in `plugins/hermes_claude_code_router/tests/test_agent_guidance_sync.py`.

---

### Defer voice routing until voice-forge is a first-order Hermes TTS provider  {#voice-deferred-until-voice-forge-first-order}

**Decision.** Phase 3 (voice routing) from the master plan is **deferred**. The router ships voice-incomplete: it'll consume voice transcripts via `pre_gateway_dispatch` (since voice + text both come through the same hook), but `voice=true` outbound replies will be either dropped or text-only until voice-forge graduates into a first-order Hermes TTS provider AND we have proven text-routing semantics end-to-end.

**Rationale.** Today, plugin out-of-band outbound (i.e., not coming through Mimir's LLM path) doesn't trigger Hermes's auto-TTS pipeline. The router would need to synth+play TTS itself (voice-forge HTTP at `:9876` or edge-tts subprocess) AND reach into `discord.py` to play via the voice client. That's a substantial subsystem (synth pipeline, queue mgmt, voice-client lifecycle, failure modes) bolted on top of an already-substantial text-routing build. Doing them sequentially keeps each phase's blast radius small + lets us validate the routing primitives before adding the synth complexity. Per Jeff: *"we could simply use edge tts for now, if voice-forge isn't deployed yet. but why add that complexity. I think we can do almost all of the router with just text. Then add voice, since really all that ends up happening is transcription of voice into text once we add voice."*

**Rejected alternatives.**
- *Ship text + voice together.* Rejected: voice adds 2-3× the complexity (synth, playback, voice-client integration, error handling on TTS timeouts). Hard to debug routing issues + synth issues simultaneously.
- *Use Edge TTS in the router as a stopgap until voice-forge integrates.* Rejected: adds throwaway code; better to wait for the first-order provider integration that Hermes already plans for.
- *Skip voice entirely + only build text routing for v1.* Rejected: voice is the whole point of the hands-free use case. We're deferring, not cancelling. The master plan's narrative is still intact.

**Revisit when.** voice-forge is registered as a Hermes TTS provider (via `ctx.register_tts_provider(...)` per [hermes-agent.nousresearch.com/docs/user-guide/features/tts](https://hermes-agent.nousresearch.com/docs/user-guide/features/tts)) AND a Mimir-LLM-driven voice reply through voice-forge is working in production. Then come back here and design how the router's out-of-band voice path uses either (a) the same provider via direct call, OR (b) Hermes's TTS subprocess-shellout pattern (per `hermes-agent._generate_neutts` → `tools/neutts_synth.py`).

**Refs.** Discussion in [LEARNINGS#out-of-band-voice-pattern](LEARNINGS.md#out-of-band-voice-pattern). Voice work queue items at [QUEUED#voice-forge-http-integration](QUEUED.md#voice-forge-http-integration), [QUEUED#discord-voice-playback](QUEUED.md#discord-voice-playback). Plan section at [`narratives/2026-05-26-router-build-plan.md`](narratives/2026-05-26-router-build-plan.md) Phase 4.

---

### Text-chat (Discord DM + channel mention + thread) is the router's FIRST milestone  {#text-chat-first-milestone}

**Decision.** The router's Phase 3 ships **text routing only**. Voice is Phase 4 (deferred per [#voice-deferred-until-voice-forge-first-order](#voice-deferred-until-voice-forge-first-order)). The text-chat surface is a first-class capability of the router — not just "scaffolding for voice."

**Rationale.** Text routing exercises the full pipeline (matcher → state mgmt → XADD inbound → XREADGROUP outbound → Discord channel.send) without the synth+playback complexity. If text routing works reliably, voice is just "transcription of voice into text" before the same routing logic kicks in. Per Jeff: *"Then add voice, since really all that ends up happening is transcription of voice into text once we add voice."*

Also: the original master plan didn't frame text-chat as a first-class deliverable — Phase 2 was "text bridge" but it was scoped as scaffolding. The Hermes Mimir profile is heavily voice-focused (Mímisbrunnr voice channel as primary), but the user can also DM Mimir in Discord, mention him in channels, and reply in threads. Those are real router-routable surfaces that don't get voice-channel coverage.

**Rejected alternatives.**
- *Treat text as scaffolding for voice; don't promote it to its own milestone.* Rejected: the user explicitly wants chat-based interaction (not just voice). Per Jeff: *"we need something in there about text capabilities (i.e. chatting in discord with the bot, not using voice)."*
- *Build text + voice together as a single Phase 3.* Rejected: see [#voice-deferred-until-voice-forge-first-order](#voice-deferred-until-voice-forge-first-order).

**Revisit when.** Never — text-chat is foundationally useful regardless of voice progress. If voice-forge first-order integration takes a long time, text-chat router remains valuable on its own.

**Refs.** Plan section at [`narratives/2026-05-26-router-build-plan.md`](narratives/2026-05-26-router-build-plan.md) Phase 3.

---

### Install via `scripts/install.sh` (copied from infiquetra-hermes-plugins pattern)  {#install-via-scripts-install-sh}

**Decision.** The plugin's deploy mechanism is `./scripts/install.sh plugin hermes_claude_code_router` — same pattern as `infiquetra-hermes-plugins/scripts/install.sh`. Copies/symlinks `plugins/hermes_claude_code_router/` into `~/.hermes/plugins/hermes_claude_code_router/`. Installs `requirements.txt` deps into Hermes's shared venv. Restart Hermes (or hot-reload via supervisor) to load the new plugin.

**Rationale.** The infiquetra-hermes-plugins pattern is the established convention for Hermes plugin development. Matching it lets users install our plugin with muscle memory from other plugins. The install.sh is a thin shim around `cp` (or `ln -s` for dev), so trivial to adapt.

**Rejected alternatives.**
- *Ansible-managed plugin install.* Rejected: plugin payloads are user-installed, not host-managed. Ansible orchestrates Hermes's runtime config (host_vars, profile env vars) but not individual plugin codebases. Mixing would muddle the boundary.
- *Python package install (pip-installable plugin).* Rejected: Hermes's plugin discovery is filesystem-scan-based (`~/.hermes/plugins/<name>/`), not package-import-based. We could publish to PyPI but Hermes wouldn't find it without a symlink/copy step anyway.

**Revisit when.** Hermes upstream changes plugin discovery (e.g., adds a `hermes plugin install <name>` first-class command). Until then, follow the cohort.

**Refs.** [LEARNINGS#hermes-plugin-install](LEARNINGS.md#hermes-plugin-install).

---

### Router protocol.py stays byte-identical to redis-channel's protocol.py  {#protocol-py-byte-identical}

**Decision.** The Pydantic models in `plugins/hermes_claude_code_router/protocol.py` MUST be byte-identical to those in `infiquetra-claude-plugins/plugins/redis-channel/server/protocol.py`. Any protocol change requires synchronized PRs in both repos.

**Rationale.** The protocol is shared between two repos (CC plugin + router) AND a third party reading the spec from PROTOCOL.md. Drift in the models = silent shape mismatches at runtime (the most painful debugging class). Keeping them byte-identical means a single source-of-truth pattern: write the model once, copy verbatim, validate via tests.

**Rejected alternatives.**
- *Publish protocol as its own Python package.* Rejected: yet-another-repo overhead for two consumers. The byte-identical copy + sync rule is lighter weight.
- *Generate protocol from a JSON Schema definition.* Rejected: same problem — adds a code-gen step for two consumers.
- *Make redis-channel a dependency of the router and import its protocol.py.* Rejected: cross-repo Python imports are fragile (paths, venvs). Better to copy.

**Revisit when.** A third or fourth router implementation appears (e.g., mobile-app router, web-UI router, Telegram router). At 3+ consumers, the copy-paste burden makes a real package worth it.

**Refs.** [LEARNINGS#redis-channel-contract](LEARNINGS.md#redis-channel-contract).

---

### Router-side state stored in plugin memory (not Redis) for routing target  {#routing-target-in-plugin-memory}

**Decision.** The routing-target state (per-user `(user_id, profile, chat_id) → session_name`) lives in the plugin's Python dict, not in Redis or a separate persistence layer.

**Rationale.** Routing target is ephemeral session state, not durable record. If the Hermes gateway restarts, the user's routing target naturally resets (they'll re-issue "connect to session foo" or whatever phrase). Putting it in Redis would survive restarts but introduce serialization concerns + an extra Redis namespace + race conditions across multiple Hermes processes (which we don't have today). YAGNI for v1.

**Rejected alternatives.**
- *Persist routing target to Redis (e.g., `routing-target:<user_id>:<profile>:<chat_id>` key).* Rejected: not needed for current single-process Hermes; revisit if we ever shard Hermes.
- *Persist to a local JSON file.* Rejected: same complexity without the multi-process benefit.

**Revisit when.** Hermes scales to multiple gateway processes that need to share routing state, OR user reports that gateway restarts losing routing target is a real pain (probably not).

**Refs.** [`infiquetra-claude-plugins/plugins/redis-channel/docs/STATE_MACHINE.md`](https://github.com/infiquetra/infiquetra-claude-plugins/blob/main/plugins/redis-channel/docs/STATE_MACHINE.md) for the state machine spec (where the state lives is router's choice; the spec is router-agnostic).

---

### Permission relay is deferred to Phase 5 (after text routing ships)  {#permission-relay-deferred}

**Decision.** The original master plan's Phase 4 (voice-only permission relay + AskUserQuestion intercept + audit logging) is deferred. Ships AFTER text routing (Phase 3) is verified end-to-end against Discord.

**Rationale.** Permission relay touches: (a) CC-side `notifications/claude/channel/permission_request` handling (already partially scaffolded in redis-channel's protocol.py), (b) router-side TTS prompt + voice STT yes/no parsing OR Discord button DM, (c) destructive-action echo-confirm, (d) audit logging on both sides. All non-trivial individually + interdependent.

Doing it after text routing ships means: we've already proven the routing primitives (matcher → state mgmt → bidirectional Redis flow → Discord I/O), so permission relay is "add another stream pair + Discord UI" rather than "design the whole pipeline + add permissions."

**Rejected alternatives.**
- *Ship permission relay as part of text routing.* Rejected: scope explosion; couples two large pieces of work.
- *Drop permission relay entirely; bypass-all-permissions in CC sessions.* Rejected: the user explicitly wants hands-free permission UX. Voice "yes/no <id>" approval is a hard requirement for the driving-while-coding use case.

**Revisit when.** Text routing has shipped + been used for ≥1 week in production. At that point, design permission relay on top.

**Refs.** master plan §4. [QUEUED#permission-relay-voice-deferred](QUEUED.md#permission-relay-voice-deferred). Audit logging cross-ref: master plan calls for JSONL audit log on both sides; format is documented in master plan + worth preserving when we implement.

---

### Phase numbering: keep master plan's numbering for traceability  {#keep-master-plan-phase-numbers}

**Decision.** The router's plan reuses the master plan's phase numbers (Phase 3 = router-side voice → reframed as text-first; Phase 4 = permission relay; Phase 5 = hybrid intelligence; Phase 6 = polish) even though we're re-scoping the contents. Doesn't renumber.

**Rationale.** The master plan ([`~/.claude/plans/i-would-like-to-distributed-hanrahan.md`](~/.claude/plans/i-would-like-to-distributed-hanrahan.md)) is the historical artifact + still the primary plan-of-record. Sub-plans that reuse its numbering stay legible against it. Renumbering would create confusion ("which Phase 3?").

**Rejected alternatives.**
- *Renumber starting from 1 in the router repo.* Rejected: loses traceability to the master plan.
- *Drop phase numbering entirely; use slug names.* Rejected: phase numbers are cognitively useful for "Phase 3 has shipped, Phase 4 is next" status conversations.

**Revisit when.** Master plan is fully shipped (every phase) and we move into v2 work; at that point renumbering for v2 makes sense.

**Refs.** Master plan at `~/.claude/plans/i-would-like-to-distributed-hanrahan.md`. Revised plan at [`narratives/2026-05-26-router-build-plan.md`](narratives/2026-05-26-router-build-plan.md).
