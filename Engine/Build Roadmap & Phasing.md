# Build Roadmap & Phasing

This document is the build plan — how the engine spec (`Director-Actor System Architecture.md`) and the hosting strategy (`Local & Hybrid Hosting Plan.md`) actually get implemented, in order, with a test gate between each phase. Nothing here changes engine design; it sequences it.

## Infrastructure decisions (settled before Phase 0)

- **Language: Python.** First-class SDKs for both Ollama and Gemini (originally chosen for Claude too; the SDK availability argument holds for either); the standard choice for this kind of orchestration glue.
- **Blackboard storage: append-only JSONL, one file per logged structure, per World Pack.** Matches the architecture doc's "structured, not prose" principle (§6/§11) — human-readable, trivially replayable, no schema migration overhead for a project this size. Reaching for SQLite is a fine later move if querying needs grow, but it's not the Phase 0 default.
- **Version control: git on the engine code**, kept separate from the in-fiction event log's own append-only history — code history and story history are two different timelines and shouldn't be conflated in one repo log.
- **Testing approach is split by what's actually testable:** the deterministic pieces (Continuity Engine's dependency-graph traversal, marks/replay, take-ledger folding) get real automated tests, since they're pure logic with no model involved. The LLM-driven pieces (Actor voice, Director arbitration judgment, prose quality) are manual review checkpoints between phases, not assertions — there's no honest automated test for "does this sound like Wen."
- **First real milestone proves turn-loop mechanics, not prose quality.** Phase 1 below is deliberately bookkeeping-first: confirm the architecture's plumbing (framing → drafting → arbitration → commit) works end to end on a trivial scene with placeholder-quality prose, before investing in getting any character's voice right. Voice/quality gets its real test once the plumbing is trusted.

## Phases

Each phase ends with an explicit test before the next phase starts. None of these are time-boxed — move on when the test passes, not on a schedule.

**Phase 0 — Scaffolding.** Set up Ollama with the chosen local model, wire in a Gemini API key, stub the model-router config from the hosting plan (role → backend mapping, even if every role points at Gemini for now). *Test:* a script calls both backends and gets a real response back from each.

> **⛔ THE ROUTER WAS NOT BUILT AT PHASE 0. It was built 2026-08-22, after Phases 1 and 2 had already run.** The clause "stub the model-router config" was skipped and nothing caught it, because a direct `ollama.chat` call works fine — the cost of the omission is invisible until a backend changes. It changed on 2026-08-17 (Gemini key deleted, Matt: *"as we build it, Claude through Claude Code needs to be the model"*), and what should have been a config edit became an edit to `actor.py`, `director.py` and `test_backends.py`, each of which independently named a vendor and could disagree with the others.
>
> **Now built** as `backends/` — `complete(role, prompt)`, adapters for `ollama` / `claude_code` / a dormant `gemini`, the role map in `backends/routing.json`, and a `preflight()` the turn loop runs before a scene starts. Both tiers verified end-to-end on 2026-08-22: an Actor drafted 2 alts through `actor_draft` on local deepseek-r1:14b in 145s, and `director_arbitration` returned well-formed arbitration JSON through Claude Code.
>
> **The general lesson, recorded because this roadmap is where a future phase would repeat it:** a phase's *seam* clauses are the ones that get skipped, because skipping them costs nothing until the thing they were meant to isolate actually moves. Test-passing is not seam-checking.

**Phase 1 — Minimal turn loop, one Actor, no takes.** Director frames a hardcoded scene, one Actor drafts alts (local model), user picks one, Director arbitrates (Gemini), the changeset commits straight to the blackboard — skip dailies/print/NG entirely for now, just write directly. *Test:* run one scene, inspect the resulting JSONL event log by hand, confirm replaying it reproduces the expected state.

**Phase 2 — Multiple Actors, filtered briefs.** Add a second and third Actor in-scene; build the brief-filtering logic that limits each Actor to what its character would plausibly know. *Test:* deliberately give one Actor a fact only another should have, confirm it doesn't leak into the first Actor's brief.

**Phase 3 — Takes, reshoots, Continuity Engine.** Add the dailies/print/NG gate, the Take Ledger, marks/replay, and a real reshoot path with the deterministic dependency-graph walk. *Test:* unit-test the graph traversal against synthetic scene histories (no LLM involved) before trusting it on a real reshoot; then run one real reshoot and confirm the conflict report matches expectations.

> **Phase 3 status, 2026-09-04 (attended session, Matt present).** Deterministic half BUILT and gated: `blackboard.py` (Take Ledger, `print_take`/`ng_take`, `marks`, active-take replay; 11 self-test cases incl. a regression that the three pre-ledger logs replay unchanged), `run_scene_take.py` (the user's print/NG call; the commit half now stages to dailies and writes nothing), `continuity.py` (forward walk over `read_facts` -> `established_facts`, transitive, `unknown-reads` for pre-Phase-3 entries; 9 synthetic-history cases). **Not yet done: the live half of the gate** -- one real reshoot with a later dependent scene, so the conflict report has something to report; and the `continuity_classify` role that turns candidates into minor/major. First observation from the real log: the Director's fact objects are free prose (`the Sleeping Hare` vs `The Sleeping Hare`), so a pure diff reads a spelling as a removal -- fact identity needs a vocabulary rule in the arbitration prompt or the World Pack before the walk is trusted on real reshoots.

**Phase 4 — World Pack versioning, locations, time model.** Wire up mid-session World Pack edits routed through the Continuity Engine, the Location State Log, and flashback/flashforward story-time handling. *Test:* edit the World Pack and confirm the right scenes get flagged; trigger a flashback and confirm Actor memory retrieval actually withholds future knowledge.

**Phase 5 — Manuscript Compiler.** Chunked compilation, both render targets (prose/screenplay), POV selection, style-sheet consistency check, render-target content filtering. *Test:* compile the same short run to both prose and screenplay and confirm the output actually differs the way §10 specifies (interiority suppressed in screenplay, etc.).

**Phase 6 — Dashboard goes live.** Replace the static `Dashboard.html` with something reading the real JSONL logs; wire up the two in-scope write actions (take purge, patch-batch amendment).

**Phase 7 — Hybrid routing for real.** Flip the model router from "everything on Gemini" (used as the safe default through Phases 1–6) to the actual local/Gemini split from the hosting plan; measure real cost, rate-limit headroom, and latency rather than estimates, and adjust the split if reality doesn't match the plan.

**Phase 8 — tiiny.ai integration.** Once the device arrives and is benchmarked (~August 2026), revisit the hosting plan's role mapping with real numbers and reroute config as warranted — no engine changes expected, per the hosting plan's design intent.

## Why Gemini-for-everything through Phase 6

Phases 1–6 deliberately don't bother with the local/Gemini split yet — every role just calls Gemini. The point of those phases is proving the architecture's logic is correct, and debugging architecture bugs is harder when you're also debugging "was that a local-model quality issue or a real bug." Only Phase 7 introduces the cost-saving local routing, once there's a working system to measure it against.

**Exception, clarified 2026-06-20:** Phase 1's own bullet above names the Actor as running on the local model specifically — this is a deliberate exception to the "Gemini for everything" default above, not a contradiction to resolve away. Matt confirmed: the Actor (Wen, via `deepseek-r1:14b`) runs local starting Phase 1; the Director's arbitration role runs on Gemini. Only the Director's role is what "Gemini-for-everything through Phase 6" actually governs.

*(Revised 2026-06-20: this section originally named Claude — swapped to Gemini since Matt doesn't currently have Claude API credits. See `Local & Hybrid Hosting Plan.md` for the full rationale; nothing about phase order or test gates changed, just the cloud vendor.)*
