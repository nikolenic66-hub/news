# Vasek group-agent behavior upgrade

Date: 2026-11-24

## Purpose

Make Vasek behave more like a coherent member of an FC Mobile Telegram group, not a generic support bot. Preserve the existing Python/httpx/Groq/SQLite deployment and the existing FC Mobile data safeguards.

## Source review

Reviewed public source and architecture from:

- [Helltar/Vusan](https://github.com/Helltar/vusan) — group-first agent design, clear distinction between direct addressing and ambient participation, reply context, and explicit silence as a valid decision. MIT license.
- [TechShreyash/ThinkMate](https://github.com/TechShreyash/ThinkMate) — persona separated from hard behavior rules, group speaker attribution, memory treated as data, cautious memory extraction, and explicit privacy boundaries. MIT license.
- [tyulyukov/groknul-bot](https://github.com/tyulyukov/groknul-bot) — recent-message context, hierarchical memory concepts, context-aware routing, and media context. No source code copied; this was architecture review only.

No foreign runtime, database, framework, API key, paid service, or private endpoint was imported. No third-party implementation code was copied into this repository. The current deployment remains Python + Telegram Bot API/httpx + Groq + SQLite.

## Changes implemented

1. Expanded `app/persona.py` with group-chat behavior:
   - Follow the actual thread instead of replying to every FC Mobile keyword.
   - Keep `[SKIP]` for messages where Vasek adds no value.
   - Do not hijack conversations between members.
   - Preserve speaker attribution and handle quoted/replied-to content as data.
   - Avoid repetitive openers, forced questions, and excessive banter.
   - Keep group memory limited to durable, non-sensitive game context.
2. Tightened `app/ai.py::summarize`:
   - Group memory is not a personal dossier.
   - Attribute preferences to the member who stated them.
   - Assistant suggestions are not evidence.
   - Ignore prompt-like instructions inside messages and memory.
   - Exclude transient jokes, rumors, sensitive data, and secrets.
3. Updated `app/__main__.py`:
   - Adds an explicit system context naming the current speaker.
   - Adds the Telegram replied-to message when it may have fallen outside stored history.
   - Labels the quoted message as untrusted data, not instructions.
   - Labels group memory as contextual data, not instructions.

## Deliberately not imported yet

- Per-person long-term profiles: current storage has group memory and activity counters, but no tested profile lifecycle or consent controls. Do not bolt on cross-chat personal memory without a separate privacy and migration design.
- Autonomous background diary / scheduled initiative engine: Vusan's implementation is much larger and would add model calls, scheduling, and operational complexity. Current low-noise activity gate and `[SKIP]` remain in place.
- Hierarchical message archive and separate router agent: Groknul's MongoDB/Node/OpenRouter/SearXNG stack is not a drop-in fit for the low-cost SQLite/Groq deployment.
- Message batching: needs a deliberate async queue and concurrency design; do not add a sleep-based debounce to the current polling handler.

## Validation

The added tests check the group persona guardrails and the safe-memory summarization contract. GitHub Actions must pass before considering this behavior upgrade verified. A CI pass does not prove Amvera deployment or real Groq response quality; those require a live bot check.
