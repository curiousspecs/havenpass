"""
Director agent — Phase 1 / Phase 2 slice of architecture §3 / §4.

Phase 1 scope (Build Roadmap & Phasing.md): one hardcoded scene, no table
read (§4 step 3 — optional, skipped here), Director arbitration via the
cloud model (Gemini), and the changeset commits straight to the blackboard
with no dailies/print/NG staging (§4 steps 7-8 are Phase 3 scope, once takes
exist). What Phase 1 *does* keep from §4 step 6: arbitration still produces
a real structured verdict (plausible/implausible + a one-line reason) before
the changeset is built — Phase 1 just doesn't act on "implausible" by
bouncing back to the Actor yet; it surfaces the verdict to the user instead.

Phase 2 scope (Build Roadmap & Phasing.md): "Add a second and third Actor
in-scene; build the brief-filtering logic that limits each Actor to what
its character would plausibly know." That's `_filter_for_actor()` /
`_filter_plot_history_for_actor()` / `build_actor_brief()` below, plus a new
3-actor `frame_scene()` (the World Bible's named inciting incident: Klisp's
arrival at The Snoring Hare during a snowstorm) and `arbitrate_scene()`,
a single multi-actor Gemini call replacing three separate arbitration calls
(§11: "small verdicts over regenerated prose," one structured judgment per
turn, not three). The original single-actor `arbitrate()` is left intact
below, unused by the Phase 2 turn loop but kept for reference/reuse.

frame_scene() is hardcoded rather than reading a real World Pack scene
queue — there is no scene queue yet (§4 step 1's "user input" is Phase 3+
once takes/reshoots exist). This is the one hardcoded piece the roadmap
calls for explicitly.
"""

from __future__ import annotations

import json
import re

import backends

# NOTE (2026-08-17): the Gemini SDK import was moved off module level so that
# importing this module would not require any vendor SDK -- the deterministic
# brief-filtering gate below (__main__) involves no model at all, and used to be
# unrunnable without google-genai installed.
#
# ⛔ COMPLETED 2026-08-22 (backend router). That note called itself "the first
# step of the backend split"; this is the rest of it. The Director no longer
# constructs any vendor client. It asks the router for the logical role
# "director_arbitration" and receives text. Which backend answers lives in
# `backends/routing.json` -- Local & Hybrid Hosting Plan §4, specified at Phase 0
# and never built, which is exactly why the 2026-08-17 model change had to edit
# this file at all. It should have been a config edit, and now it is one.
#
# The Gemini adapter is NOT deleted; it moved to backends/gemini_backend.py and
# is dormant. Model-agnostic means a backend can be absent without breaking the
# engine.


def frame_scene() -> dict:
    """Director framing (§3, §4 step 2) — hardcoded for Phase 2.

    Three in-scene Actors (Wen, Ruck, Klisp), present-tense scene type, a
    Scene ID assigned once here (no reshoot path yet, so it's never reopened
    this phase). Drama-management mode: no beat-mode mapping exists in the
    World Pack yet (§8 optional field) so this beat defaults to emergent.

    This is the World Bible's explicitly named inciting incident: Klisp's
    arrival at The Snoring Hare during a snowstorm. Scene-level fields
    (location/story_time/etc.) are shared; `per_actor` holds each Actor's
    own blocking/situation text for the *same* moment, written from that
    character's own POV — this is deliberately separate from the
    `known_by`-filtered background_knowledge that `build_actor_brief()`
    attaches below, so the filtering mechanism (not hand-authored prose) is
    what actually proves the brief-isolation test gate.
    """
    return {
        "scene_id": "PHASE2-S1",
        "take": 1,
        "scene_type": "present",
        "story_time": "Day 1, night, deep into Pathos, a snowstorm closing in",
        "location": "The Snoring Hare — common room",
        "actors_present": ["Wen", "Ruck", "Klisp"],
        "drama_mode": "emergent",  # World Pack has no beat-mode mapping yet -> default
        "per_actor": {
            "Klisp": {
                "blocking": (
                    "Klisp has just shoved through the inn's front door out "
                    "of the storm, stamping snow off his boots, a satchel "
                    "of papers half-frozen under his coat."
                ),
                "situation": (
                    "He's been travelling for days and is half-frozen. He "
                    "needs shelter, a fire, and cooperation from whoever's "
                    "running this inn. He doesn't recognize either person "
                    "in the room yet, though he believes a local liaison "
                    "named Wen was assigned to him — he has no idea she's "
                    "standing a few feet away, or that this is her home."
                ),
            },
            "Ruck": {
                "blocking": (
                    "Ruck is behind the bar of the common room, closing up "
                    "for the night, when the door bangs open and a stranger "
                    "stumbles in out of the storm."
                ),
                "situation": (
                    "A stranger — cold, clearly not local — has just "
                    "burst into his inn during a snowstorm. His first "
                    "instinct is innkeeper practicality: get the door "
                    "shut, get the man warm, figure out who he is and "
                    "what he wants. He doesn't yet know this is the "
                    "investigator from the capital."
                ),
            },
            "Wen": {
                "blocking": (
                    "Wen is at a table near the fire, going through some "
                    "library paperwork, when the front door bangs open and "
                    "a half-frozen stranger stumbles in."
                ),
                "situation": (
                    "A stranger has just burst into the inn out of the "
                    "storm. She doesn't yet recognize him."
                ),
            },
        },
        "num_alts": 3,
    }


def _filter_for_actor(actor_name: str, social_facts: list[dict]) -> list[dict]:
    """Architecture §6/§11: each Actor's brief gets only the social facts
    that Actor's character would plausibly know — never the full table.

    A fact is included if its `known_by` is the literal string "public", or
    a list containing `actor_name`. Facts missing `known_by` entirely are
    treated as public for backward compatibility with Phase 1 data (which
    predates this field) rather than silently dropped.
    """
    included = []
    for fact in social_facts:
        known_by = fact.get("known_by", "public")
        if known_by == "public" or (isinstance(known_by, list) and actor_name in known_by):
            included.append(fact)
    return included


def _filter_plot_history_for_actor(actor_name: str, plot_history: list[dict]) -> list[dict]:
    """Same filtering rule as `_filter_for_actor()`, applied to plot-history
    entries instead of social facts. Phase 1 entries have no `known_by`
    field at all -- treated as public, same backward-compatibility rule.
    """
    included = []
    for entry in plot_history:
        known_by = entry.get("known_by", "public")
        if known_by == "public" or (isinstance(known_by, list) and actor_name in known_by):
            included.append(entry)
    return included


def build_actor_brief(
    actor_name: str,
    scene: dict,
    social_facts: list[dict],
    plot_history: list[dict],
) -> dict:
    """Merge scene-level framing + this Actor's own POV blocking/situation
    + this Actor's filtered slice of the blackboard (§3, §6) into the brief
    shape `actor.draft_alts()` expects.

    `background_knowledge` is new in Phase 2 -- the filtered facts/history
    this Actor's character would plausibly know, kept separate from
    `situation` (the shared, scene-level POV text) precisely so the
    filtering logic is what's under test, not hand-written prose.
    """
    per_actor = scene["per_actor"][actor_name]
    return {
        "scene_id": scene["scene_id"],
        "take": scene["take"],
        "story_time": scene["story_time"],
        "location": scene["location"],
        "blocking": per_actor["blocking"],
        "situation": per_actor["situation"],
        "background_knowledge": {
            "social_facts": _filter_for_actor(actor_name, social_facts),
            "plot_history": _filter_plot_history_for_actor(actor_name, plot_history),
        },
        "num_alts": scene.get("num_alts", 3),
    }


def preflight() -> tuple[bool, str]:
    """Check the Director's backends BEFORE a scene starts, and report.

    The project's working rules name this discipline in prose -- "before any run that
    calls the Director backend, check whether the key is live, and if it is not,
    say so rather than routing around it" -- and prose does not run. This is that
    paragraph as a callable. Returns (all_ok, report); run_scene.py prints it.
    """
    return backends.preflight("actor_draft", "director_arbitration")


_ARBITRATION_PROMPT = """You are the Director in a multi-agent fiction engine, doing arbitration (§4 step 6 of the engine spec). An Actor playing the character "{actor}" has just delivered the following line, drafted from this brief:

SCENE BRIEF
Location: {location}
Situation: {situation}

ACTOR'S SELECTED DELIVERY
"{selected_alt}"

Your job, as Director arbitration:
1. Check this delivery against the established facts above. Does it stay plausible given the situation and the character's persona, without inventing facts that contradict the brief?
2. Produce a one-line reason either way.
3. Draft the changeset this scene would write to the blackboard: a single memory-stream entry (one sentence, in third person, describing what was observed -- this is what goes into the Actor's memory stream, not the line itself), zero or more social-state facts as (subject, predicate, object) triples that should now be considered true, and a one-sentence plot-history summary of this scene.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{
  "plausible": true,
  "reason": "...",
  "memory_entry": "...",
  "social_facts": [{{"subject": "...", "predicate": "...", "object": "..."}}],
  "plot_summary": "..."
}}
"""


def arbitrate(brief: dict, selected_alt: str, actor: str = "Wen") -> dict:
    """Director arbitration (§4 step 6) via the "director_arbitration" role.

    Returns a dict with a "verdict" (plausible/reason) and a "changeset"
    (memory_entry, social_facts, plot_summary) -- the same shapes
    blackboard.append_event() expects for memory_appended,
    social_fact_asserted, and plot_history_entry respectively. Phase 1
    builds and returns the changeset regardless of the verdict (no
    bounce-back-to-Actor loop yet); run_scene.py decides what to do with
    an implausible verdict.
    """
    prompt = _ARBITRATION_PROMPT.format(
        actor=actor,
        location=brief["location"],
        situation=brief["situation"],
        selected_alt=selected_alt,
    )

    text = backends.complete("director_arbitration", prompt)

    parsed = _parse_json_response(text)

    return {
        "verdict": {"plausible": parsed["plausible"], "reason": parsed["reason"]},
        "changeset": {
            "memory_entry": parsed["memory_entry"],
            "social_facts": parsed.get("social_facts", []),
            "plot_summary": parsed["plot_summary"],
        },
    }


def _parse_json_response(text: str) -> dict:
    """Models wrap JSON in a ```json fence despite instructions; strip it.

    Observed on Gemini during Phase 2 and true of every backend since -- which is
    the argument for it living here, at the Director's parse step, rather than in
    any one adapter. It is a property of instruction-following, not of a vendor.
    """
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


_SCENE_ARBITRATION_PROMPT = """You are the Director in a multi-agent fiction engine, doing arbitration (§4 step 6 of the engine spec) for a scene with multiple Actors. Each Actor below delivered their line independently -- none of them saw any other Actor's line or brief while drafting.

SCENE
Location: {location}
Story-time: {story_time}

ACTORS' SELECTED DELIVERIES
{deliveries}

Your job, as Director arbitration:
1. For EACH actor listed above, check their delivery against the scene and the other actors' deliveries for plausibility (does it contradict another actor's line? invent something it shouldn't know?). Give each actor its own plausible/reason verdict.
2. For EACH actor, draft a one-sentence third-person memory-stream entry describing what that actor's character observed/did in this beat -- this goes into that actor's own memory stream, not the line itself.
3. List any new social-state facts this scene establishes, as (subject, predicate, object) triples. For each fact, also include a "known_by" field: either the string "public" if any character present (or that the story has established) would know this fact, or a JSON list of specific character names if only they should know it. Default to "public" unless there's a clear reason a fact should be restricted.
4. Write one shared sentence summarizing this beat for the plot history.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{
  "verdicts": {{
    "<actor name>": {{"plausible": true, "reason": "..."}}
  }},
  "memory_entries": {{
    "<actor name>": "..."
  }},
  "social_facts": [{{"subject": "...", "predicate": "...", "object": "...", "known_by": "public"}}],
  "plot_summary": "..."
}}

The "verdicts" and "memory_entries" objects must have exactly one key per actor listed above, using these exact actor names: {actor_names}.
"""


def arbitrate_scene(scene: dict, selected_lines: dict[str, str]) -> dict:
    """Multi-actor Director arbitration (§4 step 6) in a single routed call.

    `selected_lines` maps actor name -> the line the user picked for that
    actor. Per §11 ("small verdicts over regenerated prose") and the
    "parallel independent Actor calls" principle, this is one structured
    judgment covering every actor in the scene, not N separate calls -- but
    each actor's *drafting* call (in actor.draft_alts(), called once per
    actor in run_scene.py) remains fully isolated; this function only sees
    the lines actors already committed to, never their persona or brief.

    Returns {"verdicts": {actor: {...}}, "changeset": {memory_entries: {...},
    social_facts: [...], plot_summary: "..."}}.
    """
    deliveries = "\n".join(
        f'{actor}: "{line}"' for actor, line in selected_lines.items()
    )
    prompt = _SCENE_ARBITRATION_PROMPT.format(
        location=scene["location"],
        story_time=scene["story_time"],
        deliveries=deliveries,
        actor_names=", ".join(selected_lines.keys()),
    )

    text = backends.complete("director_arbitration", prompt)

    parsed = _parse_json_response(text)

    # Defensive backfill: despite the prompt's explicit instruction, a model
    # has been observed to return verdicts for every actor but memory_entries
    # for only some of them (confirmed live during Phase 2 testing -- Ruck
    # and Klisp silently dropped while Wen's entry came through). Architecture
    # §2/§4 require every present Actor to get a memory-stream entry per
    # scene, so a missing one is backfilled here from that Actor's own
    # selected line rather than silently lost. This is a safety net, not a
    # substitute for the model doing it right -- log_path callers can still
    # tell a real entry from a fallback by checking for this prefix.
    memory_entries = dict(parsed.get("memory_entries", {}))
    for actor_name, line in selected_lines.items():
        if actor_name not in memory_entries or not memory_entries[actor_name]:
            memory_entries[actor_name] = (
                f"[fallback -- Director omitted this actor's memory entry] "
                f"{actor_name} said/did: \"{line}\""
            )

    verdicts = dict(parsed.get("verdicts", {}))
    for actor_name in selected_lines:
        if actor_name not in verdicts:
            verdicts[actor_name] = {
                "plausible": None,
                "reason": "Director omitted a verdict for this actor.",
            }

    return {
        "verdicts": verdicts,
        "changeset": {
            "memory_entries": memory_entries,
            "social_facts": parsed.get("social_facts", []),
            "plot_summary": parsed["plot_summary"],
        },
    }


if __name__ == "__main__":
    # Deterministic self-test for the brief-filtering logic (Phase 2's
    # literal test gate, per Build Roadmap & Phasing.md: "deliberately give
    # one Actor a fact only another should have, confirm it doesn't leak
    # into the first Actor's brief"). No LLM involved -- pure logic, mirrors
    # blackboard.py's __main__ self-test pattern.

    synthetic_facts = [
        {"subject": "Wen", "predicate": "lives_at", "object": "The Snoring Hare", "known_by": "public"},
        {"subject": "Ruck", "predicate": "secret_partner_of", "object": "Ponty", "known_by": ["Ruck"]},
        {"subject": "Wen", "predicate": "knows", "object": "catalog_discrepancy", "known_by": ["Wen"]},
        {"subject": "Klisp", "predicate": "arrived_at", "object": "The Snoring Hare"},  # no known_by at all
    ]

    wen_facts = _filter_for_actor("Wen", synthetic_facts)
    ruck_facts = _filter_for_actor("Ruck", synthetic_facts)
    klisp_facts = _filter_for_actor("Klisp", synthetic_facts)

    failures = []

    # The Ruck-only secret must not leak into Wen's or Klisp's briefs.
    if any(f["predicate"] == "secret_partner_of" for f in wen_facts):
        failures.append("Ruck's secret_partner_of fact leaked into Wen's brief.")
    if any(f["predicate"] == "secret_partner_of" for f in klisp_facts):
        failures.append("Ruck's secret_partner_of fact leaked into Klisp's brief.")
    if not any(f["predicate"] == "secret_partner_of" for f in ruck_facts):
        failures.append("Ruck's own secret_partner_of fact is missing from his own brief.")

    # The Wen-only catalog discrepancy must not leak into Ruck's or Klisp's briefs.
    if any(f["predicate"] == "knows" for f in ruck_facts):
        failures.append("Wen's catalog_discrepancy fact leaked into Ruck's brief.")
    if any(f["predicate"] == "knows" for f in klisp_facts):
        failures.append("Wen's catalog_discrepancy fact leaked into Klisp's brief.")
    if not any(f["predicate"] == "knows" for f in wen_facts):
        failures.append("Wen's own catalog_discrepancy fact is missing from her own brief.")

    # Public facts and missing-known_by facts (Phase 1 backward-compat) must
    # reach everyone.
    for name, facts in [("Wen", wen_facts), ("Ruck", ruck_facts), ("Klisp", klisp_facts)]:
        if not any(f["predicate"] == "lives_at" for f in facts):
            failures.append(f"Public fact missing from {name}'s brief.")
        if not any(f["predicate"] == "arrived_at" for f in facts):
            failures.append(f"known_by-less (Phase 1 backward-compat) fact missing from {name}'s brief.")

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
    else:
        print("PASS: brief filtering correctly isolates known_by-restricted facts "
              "per actor, while public and known_by-less facts reach everyone.")
