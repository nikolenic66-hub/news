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


## Follow-up continuity increment (2026-11-24)

- The handler recognizes a narrow set of short follow-up openings (for example, “а почему?”, “а если?”, “и что дальше?”) only when the immediately preceding stored message is the assistant and the bot itself replied within the last 120 seconds.
- The follow-up is treated as a direct turn, so it bypasses the ordinary spontaneous-reply lottery and the short direct-message cooldown.
- The bot reply timestamp is held in process memory; after a restart, explicit Telegram replies/name calls still work, while implicit follow-up routing resumes after the next bot response.
- This is intentionally not a general “answer every short message” rule. Tests cover positive cases, unrelated messages, stale windows, and commands.


## Group discussion and recap increment (2026-11-24)

- Ambient replies require a substantive FC Mobile message, the existing activity probability and cooldown, and are suppressed when the message is an explicit reply to a human or immediately follows a bot reply. Direct mentions, bot replies, and recognized follow-ups still take the direct path.
- Recap behavior is explicitly constrained: summarize only the history actually supplied, distinguish participants' positions, and identify a speaker only when attribution is present. Missing history must be acknowledged rather than invented.
- No extra model call, paid service, background scheduler, or database migration was introduced.

## Conversation-memory reliability increment (2026-11-24)

- The previous summary trigger waited for 60 incoming messages but passed only the default 16-message history window to the summarizer. This could silently omit much of the conversation that triggered the refresh.
- Memory refresh now runs every 30 incoming messages and reads the full retained history window (MAX_HISTORY * 3 rows).
- The summarizer keeps up to 60 recent messages, clips each message to 700 characters, and skips empty entries to bound request size.
- If summarization fails, it retries after five more incoming messages instead of resetting the counter or retrying on every single update.
- No database schema, provider, API, or deployment changes were introduced.

## RenderZ player lookup hardening (2026-11-24)

The existing public-page integration was tightened rather than replaced. Player labels are now normalized for accents and punctuation, and matching requires complete name tokens instead of a loose substring match. Explicit OVR filters remain exact; OVR-only requests do not select arbitrary cards. English player-data vocabulary and Russian-name aliases/transliteration improve request routing.

No code or data was copied from the reviewed third-party bots. The implementation continues to read ordinary public RenderZ HTML only, with existing cache, request timeout and hard verification gate. A returned card is still only as complete and current as the visible RenderZ page.

Added regression coverage for exact token matching, multi-word and accented names, transliteration, OVR-only requests and English player-data phrasing. This increment does not implement comparison workflows or squad optimization.
