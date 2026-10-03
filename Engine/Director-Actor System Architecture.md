# Director/Actor System: Engine Architecture

This document specifies the **engine** — the world-agnostic mechanics of the director/actor multi-agent fiction system. It is designed to run any story world, not just Havenpass. Havenpass-specific examples appear throughout in *(example)* call-outs purely for illustration; the actual Havenpass content lives in its own World Pack (see §8; the Havenpass world bible itself is not included in this repository), not in this file.

Synthesizes patterns from 23 papers on game AI, believable agents, drama management, social simulation, and generative agents — full source digest in *Research Digest - Agent Architecture Sources.md*.

## 1. Design Goals

- One **Director** agent: omniscient, executive. Takes the user's scenario/plot-point/story-beat input and decides which Actors are involved and what they're presented with.
- N **Actor** agents: each a fully-individuated character. Each Actor only sees what the Director gives it (its own persona, its memories, the immediate scene) and produces its own dialogue/behavior — it does not see the Director's full plot plan or other Actors' private state.
- The system should produce coherent plot *and* believable, idiosyncratic character behavior — these are often in tension (see §3), so the architecture needs an explicit mechanism for resolving it rather than hoping it falls out naturally.
- The engine must be **world-agnostic**: every piece of Havenpass-specific content (characters, setting, cosmology, plot) must be swappable by pointing the engine at a different World Pack, without touching this document.
- Nothing should be **permanently written** to shared state without a confirmation point the user controls — this applies to ordinary scene close, reshoots, and edits to the World Pack itself (see §7).
- Production should be allowed to be **nonlinear**: scenes can be shot out of order, redone, and replaced, the way a film production reshoots a scene without reshooting the whole picture (see §7).

## 2. Actor Agent Architecture

Each Actor is built from four layers, borrowed mostly from Park et al.'s generative-agents work and refined with believability research:

**Persona.** Static character sheet supplied by the World Pack: identity, voice, relationships, private goals. Per Riedl's IPOCL work, an Actor's private goal should be *distinct from* the Director's plot goal — the Actor is pursuing its own motivation, and the Director's job is to ensure the Actor's actions remain explicable in terms of that motivation (a reader/user should always be able to answer "why did this character just do that?"). *(Example: in Havenpass, Wen's goal is "solve the case for the money / out of curiosity," not "advance the mystery plot" — those usually overlap but shouldn't be conflated in the prompt.)* Because the Persona is static for the life of the World Pack, it should sit as the **stable prefix** of every Actor prompt — everything that doesn't change scene-to-scene first, the per-scene brief and retrieved memories appended after — so a platform's prompt cache can reuse it across calls instead of reprocessing it on every Actor turn (see §11).

**Memory stream.** A log of everything the Actor has observed or said, each entry stamped with **story-time** (not wall-clock time or turn count — see §5), a **scene ID + take number** (see §7), and a **narrative-sequence index** (the order it was actually told to the user — see §10), then scored at retrieval time on three axes: recency (decay measured in story-days elapsed), importance (rated once at write-time, 1–10), and relevance (embedding similarity to the current scene) — summed and normalized to pick what enters the prompt context. Retrieval runs against an explicit **budget** (a fixed entry count or token cap, not an open-ended threshold) — without one, retrieval cost grows unboundedly as a story gets longer. Within that budget, **reflections are preferred over the raw entries they were built from**: a reflection already compresses several observations into one higher-level insight, so retrieval reaches for it first and only pulls the underlying raw entries when the reflection scores as relevant but insufficiently specific. Because entries are story-time-stamped, retrieval can also be **filtered to "as of" a given story-time** rather than always pulling from the latest moment — this is the mechanism that makes flashbacks work (§5), and the same mechanism locations use (§6). Memory entries only exist in the stream once their producing take has been **committed** (§7) — a discarded take leaves no trace.

**Reflection.** Triggered **per scene** (rather than on a cumulative-importance threshold): at scene close, each in-scene Actor generates higher-level insights from that scene's memories and stores these back into the stream. Tying reflection to scene boundaries instead of a running importance total matches the discrete, episodic shape of a director-led story and keeps reflection cadence predictable. Reflections are part of the scene's changeset (§7) like any other memory write — they don't land until the take is confirmed good.

**Emotional/behavioral layer.** Per Bates' Oz work: emotional state should be visible and slightly exaggerated, not subtly "correct," because subtlety reads as inert. Per Umarov et al.: an Actor should draft 2–3 plausible behavioral options per turn rather than committing to one "optimal" response. **These options are surfaced to the user, who chooses (or requests a redraft)** — a deliberate authorial-control decision: the user keeps a hand on characterization turn-to-turn rather than the Director silently picking on their behalf.

## 3. Director Agent Architecture

The Director's job splits into five responsibilities:

**Scene framing.** Receives the user's input (a scenario, a plot beat, a constraint) and translates it into per-Actor briefs: what each Actor currently knows, who's present, what just happened. As part of framing, the Director declares the scene's **story-time** (date, time-of-day, elapsed time since the last scene — including explicit time-skip framing like "three days later"), its **scene type** (present-tense / flashback / flashforward — see §5), and assigns or re-uses the scene's **Scene ID** (see §7). Framing is about content — facts, stakes, who's present and what they know; where each Actor physically is and what they're doing as the scene opens is **blocking**, specified separately and tersely, since it's read by Actors as situational grounding rather than narrated to the user as prose. Each Actor's brief is a **filtered slice** of the blackboard — only the social-state rows, location state, and plot history that Actor's character would plausibly know or perceive in this scene, never the full tables (see §11) — which is both a fairness rule (a character shouldn't reason from facts it doesn't know) and a cost rule (a brief is never larger than what's actually needed).

**Flashback/flashforward triggering.** The user can explicitly request a flashback or flashforward at any point. The Director can *also* infer one from phrasing (e.g., "what happened to her before she came to [town]") — but when inferring, the Director must ask the user to confirm before staging it, rather than silently jumping in story-time. This confirmation step is the one piece of "bookkeeping" that surfaces to the user during otherwise-invisible scene-setting, because it changes what the user is about to see.

**Drama management.** Two opposed patterns exist in the research:
- *Emergent (Aylett)*: don't script outcomes; let Actors act on their own drives, with the Director only nudging coherence via a light "social pressure" signal.
- *Plan-mediated (Brenner)*: the Director maintains a shared plan, but an Actor's action only "counts" if that Actor's own preconditions are satisfied — Actors can refuse or renegotiate, and the "plot" becomes a causally-annotated history reconstructed *after* the fact.

  Which mode applies to which kind of beat is a **World Pack setting**, not an engine default (see §8) — *(Havenpass example: plan-mediated for mystery-structure beats, emergent for relationship/banter beats)*. The Director tags each beat with its active mode so Actors and the user know how much an Actor can deviate. The causal annotations the plan-mediated mode produces double as the **dependency graph** the Continuity Engine walks during reshoots and World Pack edits (§7).

**Social state tracking.** Borrowed from *Comme il Faut*: maintain an explicit, global social-state table — relationships, per-dyad scalar affinities, standing statuses, and a fact database of who-knows-what. The Director updates this after every scene and consults it before framing the next one.

**Take gating.** Before any of the above becomes permanent, the Director asks whether the take was good (§7). This is a fifth, cross-cutting responsibility rather than a step that happens after the other four — it's the gate all of them pass through before committing.

## 4. Turn Loop

1. **Input.** User gives the Director a scenario / beat / constraint.
2. **Framing.** Director consults the social-state table and plot history, declares the scene's story-time and scene type, assigns a Scene ID (new scene) or reopens an existing one (reshoot), decides which Actors are in-scene, and writes each a private brief. If the Director infers a flashback/flashforward from the user's phrasing, it asks for confirmation here before proceeding.
3. **Table read (optional, complex/high-stakes beats only).** Before paying for full alt-drafting, the Director can run a cheap rehearsal pass: a short, low-token check of the beat's setup — who's present, what's at stake, whether plan-mediated preconditions actually hold — to catch an implausible setup before any Actor drafts full behavioral alts. This is a judgment call the Director makes per beat, not a step every scene runs: routine banter skips straight to step 4, while a confrontation, a reveal, or a major plan-mediated beat is the kind of thing worth a table read first. A table read that finds a problem sends the Director back to step 2 to reframe, before any Actor call is spent.
4. **Actor generation.** Each in-scene Actor retrieves memories — filtered "as of" the scene's declared story-time first, then scored by recency/importance/relevance within its retrieval budget (§2) — and drafts 2–3 behavioral **alts** (alternate deliveries of the same take, not separate takes — see §7) including emotional tone. When more than one Actor is in-scene, these run as independent, parallel calls — no Actor's prompt ever carries another Actor's persona or brief (see §11).
5. **User selection.** The drafted alts for each Actor are surfaced to the user, who picks one (or asks for a redraft).
6. **Director arbitration.** Director checks the selected outputs against the World Pack's established facts and the scene's drama-management mode; if an action is implausible or violates a plan-mediated precondition, it's bounced back to the Actor for a revision rather than silently overwritten. This check produces a small, structured verdict — plausible/implausible plus a one-line reason — never a regenerated scene (see §11).
7. **Changeset staged.** Director assembles everything the scene would write — memory appends and reflections, social-state deltas, location-state deltas (§6), the plot-history entry, any retcon entries — into a **changeset** tagged with this scene's ID and take number, and holds it in **dailies** (§7). Nothing here is written to the blackboard yet.
8. **Take confirmation.** Director calls it: **print**, or **NG** (no good) (§7).
   - *Print*: the changeset commits — it becomes part of the permanent, event-sourced blackboard, and this take becomes the active one for its Scene ID.
   - *NG*: the changeset is discarded. Nothing changed, so Actors and locations are already **back to one** — no explicit reset step is needed. The scene reruns as a new take under the same Scene ID, returning to step 4.
9. **Output.** Director composes the scene for the user, tagging Director (narration/framing) vs. Actor lines, with the scene's story-time header shown so flashbacks/flashforwards read as visually distinct from "now." All of the above bookkeeping (steps 2–3, 6–8) stays invisible to the user except where it changes what's shown or asks for a decision — this whole loop is what "setting the scene" means in user-facing terms.

## 5. Time Model: Story-Time, Flashbacks, and Flashforwards

**Story-time as a first-class field** (informally, the story's **chronology** — see the glossary, §12). The Director stamps every scene with story-time (date/time-of-day/elapsed-since-last-scene), decoupled entirely from real-world conversation turns or wall-clock time. Memory entries inherit this stamp. Recency decay in retrieval is computed against *story-days elapsed*, not turns-since.

**Flashbacks** fall out of this almost for free: a flashback scene is declared at an earlier story-time, and each Actor's memory retrieval is **hard-filtered to entries timestamped at or before that scene's time** before the usual recency/importance/relevance scoring runs. An Actor genuinely doesn't "know" things in a flashback they haven't learned yet in-story, even though their full memory stream already contains later entries. Location state (§6) uses the identical as-of filter.

**Flashforwards are Director-authored.** The Director stages the flashforward directly, briefly bypassing normal Actor memory-driven generation, rather than having Actors speculatively generate ungrounded future behavior. Every flashforward is logged with status `pending`. When the story's actual timeline later reaches that point, the Director resolves the flag to either `fulfilled-as-shown` or `diverged` (actual events played out differently) — this resolution is itself a normal beat with its own narrative-sequence position, not a retroactive edit (see §10).

**Retroactive changes (the retcon log).** When a flashback reveals that a previously-implied event was different than shown, or a flashforward resolves as `diverged`, the system needs an explicit **retcon log** rather than silently rewriting history. Each entry records: the original fact, the revised fact, the scene that triggered the revision, and which prior scenes/entries are flagged for continuity review. **Existing Actor memory entries are never edited in place** — a retcon is appended as a *new* memory ("I realize now that what I saw wasn't what I thought"), the same way a reflection layers a higher-level insight on top of raw observations. This keeps the recency-weighted retrieval math sane and mirrors how people actually update beliefs.

**Retcon vs. reshoot vs. World Pack patch — three different "fix" mechanisms, not one.** These are easy to conflate and need to stay distinct:
- A **retcon** (above) is an *in-fiction* correction: the story itself reveals something was different than it first appeared. The original scene's content is preserved exactly as told — only the reader's understanding is layered on top, at its own later narrative position. Nothing already shown is discarded.
- A **reshoot** (§7) is an *out-of-fiction* production decision: the user decides a scene's actual content should change. The prior take is discarded outright — it never "happened," the way discarded film footage never made the cut.
- A **World Pack patch** (§8) is also out-of-fiction: a continuity-preserving tweak the Continuity Engine suggests to an already-committed scene so it stays consistent after a World Pack edit, without reshooting it.

It's possible for these to interact: if a retcon was logged referencing a fact a scene established, and that scene is later reshot in a way that no longer establishes that fact, the retcon entry is orphaned. The Continuity Engine's reshoot check (§7) always surfaces this to the user as a flagged conflict rather than silently leaving a dangling retcon or auto-retiring it — an orphaned retcon is exactly the kind of judgment call ("does this still matter to the story, reframed, or should it be dropped") that stays with the user.

## 6. World State: Social Facts, Locations, and the Blackboard

A single shared store, modeled on Soar's blackboard pattern. Everything mutable in it — social-state table, location state, memory streams, plot history — is modeled as an **append-only log of events**, each event tagged with the Scene ID and take number that produced it. "Current state" of anything is always a fold/replay of committed events, in story-time order, using only the active take for each Scene ID. This is what makes takes cleanly discardable (§7): a discarded take's events simply never get folded in, with no separate undo logic needed per structure.

The blackboard holds:
- The **World Pack** — versioned, user-editable per-story facts: cosmology, geography, established backstory, personas, location baselines (supplied externally and editable at any time, see §8 — no longer treated as immutable).
- The **social-state table** (Director-owned event log of relationships, statuses, traits, fact-database entries).
- **Location state** (see below).
- The **plot history** (append-only causal log; each entry carries a story-time stamp, a narrative-sequence index, scene-type/resolution flags, and the causal links — what facts it read, what it established — that the Continuity Engine treats as the dependency graph).
- The **retcon log** (append-only — revised facts, what triggered them, which prior entries they affect; see §5 for how this differs from a reshoot).
- The **Take Ledger** (§7) — every take of every Scene ID, which one is currently active, and each take's changeset. Discarded takes are retained by default rather than deleted on discard; the user can select one or more specific discarded takes from the ledger and purge them explicitly — purging is always a deliberate, user-initiated action, never automatic.

**Locations as persistent, mutable world objects.** A location's *baseline* description lives in the World Pack — e.g. *(Havenpass example: "The Snoring Hare: a worn inn with a communal hearth")*. Anything that changes during play — a wall gets damaged, a room gets redecorated, a building burns down — is recorded as an entry in the **Location State Log**, using the same event-sourced, scene/take-tagged model as everything else (this plays the same role a film's **art-department continuity log** plays on a real set — a record of exactly how a space looked at a given point, kept apart from the script). A location's *current* description at any point is the World Pack baseline plus the fold of all committed Location State Log entries for that location up to the relevant story-time — folded in **story-time order**, not narrative-sequence order, and subject to the same "as-of" filter Actor memory uses (§5): a flashback set before the inn was damaged sees the undamaged inn, regardless of when the damage was actually committed in real conversation time. Location changes participate fully in the take/reshoot system (§7) and in World Pack edits (§8) exactly like any other state — if the scene where a wall is damaged gets reshot without the damage, the Continuity Engine checks whether any later scene referenced that damage and flags it like any other conflict.

**No implied offscreen state.** An Actor or location not currently in-scene doesn't quietly change in the background — nothing updates without a scene (or an explicit Director-authored beat) producing the changeset that updates it. If the user wants to know what Bryony's stall was doing while she was offscreen, that's a beat to frame, not an inference the engine makes silently. This keeps "nothing commits without a confirmed take" (§7) airtight — there's no backdoor path to a change that never passed through dailies.

**Keep the blackboard structured, not narrated.** Social-state and location-state entries are terse structured records (subject, predicate, object, story-time, source Scene ID) — not prose. A fact table is cheap to inject into a brief and cheap for the Continuity Engine to diff; prose is expensive and ambiguous to re-parse. Narration happens at exactly two points that need it: a filtered slice of these facts inside an Actor's brief (§3), and the Manuscript Compiler's output (§10) — nowhere else on the blackboard (see §11).

Actors read from the World Pack and their own persona/memory; they do not read each other's private memory streams or the Director's plot plan directly — anything one Actor needs to know about another must arrive through in-scene observation or the Director's framing.

## 7. Takes, Reshoots, and the Continuity Engine

Scene close (§4) doesn't write straight to the blackboard — everything passes through a staging buffer first, gated by an explicit take-confirmation step. This is what makes bad takes discardable and earlier scenes reshootable without corrupting later ones.

**Scene identity.** Every scene gets a stable **Scene ID** at the moment the Director first frames it — independent of both story-time and narrative-sequence position, the same way a screenplay slate number is independent of shooting order. A Scene ID can be reshot any number of times; each attempt is a numbered **take** under that same ID. Together, {Scene ID, take number} form the scene's **slate** — exactly what a clapperboard records on a real set ("Scene 14, Take 2"). Exactly one take per Scene ID is ever active in current state at a time.

**Marks.** A scene's "marks" — the state every Actor and location is in at the moment the scene starts — are simply the replay of all committed events up to (not including) that scene's own events. Because state is event-sourced (§6), marks don't need to be separately snapshotted to be restored; caching the replay at scene-start is a reasonable implementation detail, not a requirement. This is also what makes "**back to one**" free: nothing committed on an NG take, so there's nothing to undo.

**Ordinary take confirmation (§4 step 7).** At scene close, the changeset sits in **dailies** — reviewed footage that hasn't been cut into the picture yet. The Director calls it:
- **Print**: the changeset's events commit; the Take Ledger marks this take active for its Scene ID.
- **NG** (no good): the changeset is discarded outright. Since nothing committed, the Actors and locations are already back to one — no explicit reset step is needed. The scene reruns as a new take.

**Reshooting an earlier scene.** The user can request this for any previously-shot Scene ID at any time, not just the most recent one:
1. The engine computes that scene's marks (replay up to, not including, its currently active take's events).
2. The scene reruns from those marks with new input/choices (§4 steps 2–6), producing a new take's changeset — staged in dailies, not committed.
3. The **Continuity Engine** diffs the new changeset against the old active take's changeset, then walks the plot history's causal-link graph (§3, §6) forward to find every later scene that read or depended on a fact the old take established and the new take changes or removes. This walk is a deterministic graph traversal over structured plot-history metadata — not a fresh LLM read of the whole plot history (see §11). The LLM is invoked afterward, only on the narrowed candidate set the traversal surfaces, to classify severity and draft patches.
4. Each affected later scene is classified:
   - *unaffected* — no dependency on the changed fact.
   - *minor* — depends on it, but the Continuity Engine can draft a small patch (a reworded line, an adjusted detail) that preserves continuity without reshooting.
   - *major* — depends on it heavily enough that the Continuity Engine recommends that scene also be reshot.
5. The user reviews this conflict report before anything commits — minor patches as a single batch list the user can freeform-amend before giving one approval (same pattern as World Pack edits, §8). On approval: the old take is superseded (excluded from future replay), the new take commits (it's "printed"), approved minor patches commit, and any scenes flagged major are queued for the user to reshoot (reshooting is never auto-triggered — it's always a user-initiated action, consistent with the take-confirmation principle in §4).

This is the same dailies-then-print/NG shape as ordinary scene close — the difference is only that the marks being returned to belong to a scene further back in the committed history, and that a conflict report is interposed before commit because other scenes may already depend on what's being replaced. The identical Continuity Engine is reused for World Pack edits (§8); in effect, it's an automated **script supervisor** — the on-set role whose entire job is tracking what's been established, what changed between takes, and what needs a continuity note for the next scene.

## 8. World Pack Interface (engine/story-data separation)

The engine (this document, the research digest, and the dashboard in §9) is meant to run unmodified against any story. A **World Pack** is everything that changes when you swap stories, and lives in its own folder (e.g. `Worlds/<name>/`) rather than mixed into the engine docs. A World Pack supplies:

- **World bible**: setting/cosmology, locations (baseline descriptions — see §6 for how they change during play), plot/mystery structure, tone & inspirations — free-form, but should be a single reference document an Actor or Director prompt can cite. *(Havenpass's is the Havenpass World Bible, which is not published in this repository.)*
- **Persona set**: one entry per Actor, each with identity, voice, private goals, relationships to other Actors, and any secrets — this is what gets loaded into each Actor's system prompt.
- **Initial social-state seed**: starting relationships/statuses/traits per character pair, before any scenes have been played.
- **Beat-mode mapping** *(optional)*: which categories of beat use plan-mediated vs. emergent drama management for *this* story (Havenpass maps mystery-structure beats to plan-mediated and relationship/banter beats to emergent; a different story might split it differently or add more categories). If a World Pack omits this entirely, every beat defaults to **emergent** drama management — plan-mediated mode is something a World Pack opts into per beat category, not a fallback.
- **Style sheet** *(optional)*: a short list of cross-cutting prose conventions for *this* story — preferred tense and person (e.g. past tense, third person), spelling/naming conventions (a character or place name with a variant spelling, hyphenation calls), and tone guardrails (e.g. Havenpass's "cozy, not gory" violence ceiling). Both Actors (so dialogue/description stays in-register) and the Manuscript Compiler (§10) check against it, which is what keeps prose consistent across many separate Actor calls and many compile sessions rather than relying on each call to independently "remember" the same conventions. If omitted, no style constraints are enforced beyond what's implicit in the world bible and personas.

The first three items (world bible, persona set, initial social-state seed) are the **minimum required World Pack**; beat-mode mapping and the style sheet are the only optional fields, and each has a well-defined default (emergent drama management; no enforced style constraints) rather than being an error when omitted. *(Industry terminology already lines up here: a World Pack is functionally a* **show bible** *— the reference document a writers' room or production keeps to hold canon across episodes. Havenpass's own file is named accordingly.)*

**The World Pack is versioned, not immutable.** The user can edit any of the above — character descriptions, location baselines, structure, tone, inspirations — at any point, not just at setup. An edit doesn't write straight through either; it follows the same staging-then-confirm shape as a reshoot:
1. The edit is staged as a diff against the current World Pack version.
2. The **Continuity Engine** (§7) checks every committed scene's established facts and preconditions against the revised World Pack, classifying each scene *unaffected* / *minor* / *major* exactly as it does for a reshoot.
3. Minor conflicts get a suggested continuity patch; major conflicts get a reshoot recommendation. Both are presented to the user before anything commits — minor patches as a single batch list rather than one confirmation per patch, since a World Pack edit can touch dozens of scenes. The user can freeform-prompt changes to that list (drop a patch, reword one, ask for an alternative) before giving one batch approval; nothing in the list commits until that approval.
4. On approval: the new World Pack version commits (the prior version is retained in a version history rather than overwritten, matching the append-only philosophy used everywhere else on the blackboard), along with any approved patches; flagged scenes queue for optional reshoot.

Swapping in a *different story* should still only ever mean pointing the Director at a different World Pack folder — nothing in §1–7, §9, or §10 should need to change. Editing the *current* story's World Pack in place is now a first-class, supported operation rather than something that requires touching the engine.

## 9. Inspector / Dashboard

A **read-only** (for now) interface for viewing everything the engine tracks, kept deliberately separate from in-scene play: during actual turns ("scene-setting"), all bookkeeping stays invisible per §4; the dashboard is where it becomes visible on demand. It should surface, per active World Pack:

- The World Pack itself (world bible, personas) and its version history (§8).
- The current social-state table.
- The current location states, alongside each location's World Pack baseline (§6).
- The plot history (in both story-time order and narrative-sequence order — these differ once flashbacks/flashforwards are in play).
- The retcon log.
- The **Take Ledger** — every Scene ID, its take history, and which take is currently active; useful for the user to compare a discarded take against the one that replaced it.
- Each Actor's memory stream (raw observations and reflections).
- Any compiled manuscript exports (§10).

A first static pass lives at `Dashboard.html` in the project root. **Scoped to one active World Pack at a time** — the dashboard doesn't show multiple Worlds side by side — but it should offer a control to close the current World and load a different one; that's a deliberate switch action, not concurrent multi-World viewing.

It's read-only for the bulk of the blackboard (social-state table, plot history, retcon log, memory streams, World Pack content) by construction right now — a future version could support editing those directly through the dashboard rather than through this conversational flow, but that's out of scope until the engine itself is implemented and running real sessions. Two narrower write actions are already in scope, though, since they're closer to housekeeping than to authoring: **purging selected discarded takes** from the Take Ledger (§6), and **freeform-amending a pending batch of minor continuity patches** before approving it (§7, §8). Both still require explicit user action to take effect — nothing purges or commits on its own.

## 10. Manuscript Compiler

The goal: turn a played-out sequence of scenes into a coherent short story, novel, or screenplay — a separate output artifact from the live blackboard state, not a replacement for it.

**Compiles from committed takes only.** The compiler reads the plot history, which by construction only contains the currently active take for each Scene ID (§7) — discarded takes never appear, and a reshoot transparently swaps which content occupies that Scene ID's slot in the manuscript. The Take Ledger's discarded-take history is available on the dashboard for the user's own reference (e.g. comparing alternate versions of a scene) but isn't part of the default compiled output.

**Two orderings, not one.** Every scene already carries a story-time stamp (§5, diegetic clock — informally the **story chronology**) and a narrative-sequence index (§4/§6, the order it was actually told — informally the **cut order**; see glossary, §12). For a linear story these move together; once flashbacks/flashforwards are used, they diverge by definition — a flashback has an earlier story-time than its surrounding narrative-sequence position, and a flashforward has a later one. **The compiler renders in narrative-sequence (cut) order, not story-time (chronological) order** — i.e., it reproduces the order things were actually told to the user, which is what makes a flashback read as a flashback rather than getting silently re-sorted into chronological position.

**Order-preserving composition.** Composed prose for already-told scenes is never rewritten when a later retcon or flashforward-resolution occurs. A retcon surfaces at its own narrative-sequence position, exactly like a normal reveal — the retcon log is a continuity-tracking tool for the Director and the dashboard, not an editor of finished prose. This matches how published fiction actually handles reveals: the reader's experience of "I was wrong about that" is itself part of the narrative, not something to be erased from earlier pages. A reshoot is different in kind from a retcon (§5) — it replaces what the manuscript renders for that Scene ID outright, since the prior take never "happened" rather than having been narratively superseded.

**No default render target.** The compiler never silently picks a format — if the user asks to "compile this into a story" without specifying, the Director always asks which target (short story / novel / screenplay) before compiling.

**Render targets.** A format adapter sits between the scene log and the output:
- *Short story / novel*: prose narration interleaving Director framing and Actor dialogue/action, with story-time headers rendered as scene breaks or chapter markers (e.g. "Three days later...").
- *Screenplay*: sluglines (location/time-of-day derived from the story-time stamp), character cues, dialogue, and action lines, following standard screenplay formatting.

**Render-target content filtering.** The same scene log compiles differently depending on target, not just differently *formatted*. Screenplay format can't show a character's unstated interior thought directly — so for screenplay output, the compiler suppresses stated interiority and forces any subtext to be externalized into action or dialogue (a character's doubt has to show as a hesitation, a deflected line, a physical tell, not a narrated "she wondered if..."). Prose output can retain more internal narration, since interiority on the page is native to the form. Both targets compile from the identical underlying scene log and changesets (§7) — only the adapter's filtering behavior differs.

**POV / narrator selection.** At compile time (prose targets only — screenplay has no narrator), the user chooses which character's point of view narrates each scene, rather than the compiler defaulting to an omniscient or fixed voice. A scene can be told tight-third from one character even though multiple Actors were in it; the compiler renders only what that POV character perceived or could plausibly infer, the same filtering logic already used for Actor briefs (§3), applied here to prose output instead of to a live prompt. POV can stay fixed on one lead for the whole manuscript or rotate scene-by-scene — the user decides per compile, and a World Pack's style sheet (§8) can record a default if the story has one.

**Style-sheet consistency check.** If the World Pack supplies a style sheet (§8), the compiler checks rendered prose against it (tense, naming/spelling conventions, tone ceiling) as part of compilation — this is what keeps a "cozy, not gory" guardrail or a consistent spelling of a character's name holding across many separate compile calls, not just within one.

**Compilation is incremental and re-runnable.** "Compile up to scene N" produces a manuscript draft from everything played so far; re-running it after more scenes are played extends the draft rather than starting over, since the underlying scene log is append-only. Re-running it after a reshoot or World Pack patch regenerates only the affected portion.

**Cuts, not one-shot renders.** A partial compile ("up to scene N") is the manuscript's **assembly cut** — a first-pass ordering of everything shot so far, no polish applied. Compiling the complete story end to end produces a **rough cut**; a further polish pass (line-level prose tightening, transition smoothing) on top of that produces a **final cut**. For long-form output, the compiler renders in chunks (e.g., chapter-sized spans) rather than attempting the whole work in one call — each chunk's prompt needs the raw scenes for that chunk plus a short recap of what's already been compiled, not the entire manuscript-so-far (see §11).

**Editorial reorder/trim pass.** Distinct from a reshoot and from the polish pass above: an optional pass at the compiler level that resequences or trims for pacing — moving a scene earlier, cutting a slow stretch, tightening a transition — without changing any underlying scene content, fact, or changeset. It edits the *manuscript's* assembly of scenes, the way a film editor recuts footage without reshooting it; the plot history and blackboard (§6) are untouched, so this never triggers the Continuity Engine (§7) the way an actual reshoot does. This pass operates on a rough or final cut and produces a new cut, never on dailies.

## 11. Engine Efficiency Principles

These cut across every section above; collected here so they read as one stance on token/context cost rather than scattered asides.

- **Stable prefixes, cached.** Every Actor prompt puts what doesn't change (Persona, §2) first and what changes every turn (brief, retrieved memories) last, so a platform's prompt cache can reuse the static prefix across calls instead of reprocessing it each turn.
- **Bounded retrieval, reflections first.** Memory and location-state retrieval (§2, §6) run against an explicit budget, not an open-ended one — and reach for compressed reflections before raw entries, since a reflection already did the compression work once.
- **Structured blackboard, prose only at the edges.** Social-state, location-state, and plot-history entries are terse structured records, not prose (§6) — narration happens only inside a filtered Actor brief and at the Manuscript Compiler (§10), never in between.
- **Filtered briefs, not full dumps.** An Actor's brief is the slice of the blackboard its character would plausibly know in this scene (§3) — never the whole social-state table or full location history.
- **Deterministic search, LLM judgment.** Anything that looks like "find every scene affected by this change" — the Continuity Engine's dependency walk (§7, §8) — is a graph traversal over structured data, not an LLM scan of the whole plot history. The LLM is invoked only on the narrowed candidate set, to classify and draft, never to search.
- **Parallel, independent Actor calls.** When multiple Actors are in-scene, their alt-drafting (§4) runs as separate, parallel calls — never one call carrying every in-scene Actor's persona at once.
- **Small verdicts over regenerated prose.** Director arbitration (§4) produces a structured plausible/implausible judgment with a short reason, not a rewritten scene.
- **Chunked, incremental compilation.** Manuscript compilation (§10) runs in chapter-sized chunks with a short recap of prior chunks, not as one call against the entire scene log.
- **Cheap rehearsal before expensive drafting.** A table read (§4, step 3) is a short setup-only check the Director can run on a complex or high-stakes beat before any Actor drafts full alts — catching an implausible setup for the cost of one small call rather than discovering it after 2–3 full alts per Actor have already been generated.

## 12. Filmmaking Glossary

The engine already borrowed scene/take/reshoot language from film production; this collects the full mapping so the vocabulary stays consistent across the spec.

| Engine concept | Film term | Meaning here |
|---|---|---|
| Scene ID + take number | **Slate** | The {Scene ID, take} pair uniquely identifying one attempt at one scene — a clapperboard slate ("Scene 14, Take 2"). |
| Staging area before commit | **Dailies** | Where a take's changeset sits after it's shot, before the Director decides whether it's kept. |
| Take confirmed good | **Print** | The Director's call that commits a take's changeset to the blackboard. |
| Take discarded | **NG (no good)** | The Director's call that discards a take's changeset; nothing committed, so nothing needs undoing. |
| Returning to a scene's pre-shot state | **Back to one** | Actors and locations are already at their marks once a take goes NG — there's no reset to perform. |
| Drafted behavioral options within one take | **Alts** | Alternate deliveries of the same take (2–3 options per turn), distinct from a full new take. |
| Pre-scene snapshot | **Marks** | The replayed blackboard state immediately before a scene's own events. |
| Continuity Engine | **Script supervisor** | The on-set role that tracks what's been established and flags inconsistencies between takes and scenes — automated here as the dependency-graph walk in §7/§8. |
| World Pack | **Show bible / production bible** | The reference document a production keeps to hold canon; already reflected in the file's own name, *Havenpass World Bible*. |
| Location State Log | **Art-department continuity log** | A record of exactly how a set/location looked at a given point, kept apart from the script itself. |
| Narrative-sequence index | **Cut order** | The order scenes are actually assembled and shown to the user. |
| Story-time | **Story chronology** | The in-universe diegetic clock, independent of cut order. |
| Partial compile ("up to scene N") | **Assembly cut** | A first-pass ordering of everything shot so far, unpolished. |
| Full compile, no polish pass | **Rough cut** | The complete story, assembled but not line-edited. |
| Full compile plus a polish pass | **Final cut** | The rough cut after a prose/line-level tightening pass. |
| Who's-where-doing-what at scene open | **Blocking** | Distinct from framing (§3) — physical/situational staging, not narrative content. |
| Cheap setup-only check before full Actor drafting | **Table read** | A rehearsal pass on a complex/high-stakes beat (§4) that catches an implausible setup before paying for full alt-drafting. |
| Post-hoc pacing pass that doesn't touch underlying content | **Recut** | The editorial reorder/trim pass (§10) — resequences or trims a compiled cut without changing any scene's content or facts. |

## 13. Remaining Open Design Questions

All six questions raised in the second round (default render target, minimum World Pack, multi-world dashboard, discarded-take retention, minor-patch confirmation at scale, orphaned retcons) are resolved and folded into §6–§10 above. None currently outstanding — this section stays as the place new ones land as the spec keeps evolving.
