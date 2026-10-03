"""
Actor agent — Phase 1 / Phase 2 slice of architecture §2 / §4 step 4.

Phase 1 scope: one Actor, local model only (Ollama), drafts 2-3 alts for a
single hardcoded brief. No memory stream / reflection / retrieval budget
yet — those are real per §2, but Phase 1's job is proving the turn-loop
*mechanics* (Build Roadmap: "proves mechanics first, not voice/prose
quality"), so this Actor only has the two layers Phase 1 actually exercises:
Persona (static, from the World Pack) and the per-scene brief the Director
hands it. Memory/reflection/emotional-layer wiring is later-phase scope.

Phase 2 adds rendering of `brief["background_knowledge"]` if present (see
director.py's `build_actor_brief()`) — this Actor's own filtered slice of
social facts / plot history, distinct from the shared `situation` text.
`_brief_text()` stays backward-compatible with Phase 1 briefs, which don't
have this key at all.

⛔ 2026-08-22 (backend router): this Actor NO LONGER NAMES A MODEL OR A VENDOR.
It asks the router for the logical role "actor_draft" and receives text. Which
backend answers is `backends/routing.json`, per Local & Hybrid Hosting Plan §4,
which specified this router at Phase 0 and never got it built — which is why
the 2026-08-17 model change had to edit engine files at all.

The routing table still points actor_draft at Ollama, and it should: §4 puts
this role local precisely because it is the highest-volume call in the whole
turn loop — 2-3 alts, per Actor, every turn.

Think-block stripping (deepseek-r1 emits <think>...</think> before its real
answer) has MOVED into the Ollama adapter, where model-specific knowledge
belongs. _strip_think() stays here and is now a harmless idempotent second
pass — removing it in the same change that moved it would have made a routing
change and a behaviour change indistinguishable in one diff.
"""

from __future__ import annotations

import re

import backends

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    return _THINK_BLOCK.sub("", text).strip()


def _persona_prefix(persona: dict) -> str:
    """Render a persona dict into the stable system-prompt prefix (§2, §11).

    This is the part of the prompt that never changes scene-to-scene, so it
    always goes first — Phase 1 doesn't have prompt caching wired up, but
    keeping the shape right now means Phase 2+ can add caching without
    restructuring the prompt.
    """
    relationships = "\n".join(
        f"  - {who}: {desc}" for who, desc in persona["relationships"].items()
    )
    secrets = "\n".join(f"  - {s}" for s in persona.get("secrets", []))
    return (
        f"You are {persona['full_name']}, a character in a story. Stay fully "
        f"in character; never break character or refer to yourself as an AI.\n\n"
        f"Identity: {persona['identity']}\n\n"
        f"Voice: {persona['voice']}\n\n"
        f"Your private goal (this is YOUR motivation, not the plot's): "
        f"{persona['private_goal']}\n\n"
        f"Relationships:\n{relationships}\n\n"
        f"Things you know that must not leak into your dialogue or "
        f"awareness unless the scene explicitly reveals them:\n{secrets}"
    )


def _background_knowledge_text(background_knowledge: dict) -> str:
    """Render this Actor's filtered slice of the blackboard (§3, §6) — only
    the facts/history this character would plausibly know, already filtered
    by director.py's `_filter_for_actor()` before it ever reaches this
    prompt. This function does no filtering itself; it only formats.
    """
    lines = []
    facts = background_knowledge.get("social_facts", [])
    if facts:
        lines.append("Things you know to be true:")
        for fact in facts:
            lines.append(f"  - {fact['subject']} {fact['predicate']} {fact['object']}")
    history = background_knowledge.get("plot_history", [])
    if history:
        lines.append("Relevant past events you're aware of:")
        for entry in history:
            lines.append(f"  - {entry['summary']}")
    return "\n".join(lines)


def _brief_text(brief: dict) -> str:
    """Render the Director's per-scene brief (§3) as the prompt's variable suffix.

    `background_knowledge` is optional and absent from Phase 1 briefs —
    only rendered (and only added to the prompt at all) when the Director
    supplied it, so this stays backward-compatible.
    """
    text = (
        f"Scene: {brief['scene_id']}\n"
        f"Story-time: {brief['story_time']}\n"
        f"Location: {brief['location']}\n"
        f"Blocking (where you are, what you're doing as the scene opens): "
        f"{brief['blocking']}\n\n"
        f"What's happening / what you currently know:\n{brief['situation']}"
    )

    background_knowledge = brief.get("background_knowledge")
    if background_knowledge:
        rendered = _background_knowledge_text(background_knowledge)
        if rendered:
            text += f"\n\n{rendered}"

    text += (
        f"\n\nDraft {brief.get('num_alts', 3)} distinct alternate deliveries "
        f"(alts, per the engine's terminology) of your reaction — your "
        f"character's actual dialogue and/or action, not narration about "
        f"you. Make them genuinely different in tone/approach, not minor "
        f"rewordings of each other. Format your reply as a numbered list, "
        f"exactly one alt per number, nothing else."
    )
    return text


def draft_alts(persona: dict, brief: dict) -> list[str]:
    """Call the local model and return a list of alt strings (§4 step 4)."""
    system_prompt = _persona_prefix(persona)
    user_prompt = _brief_text(brief)

    raw = backends.complete("actor_draft", user_prompt, system=system_prompt)
    cleaned = _strip_think(raw)
    return _split_numbered_alts(cleaned)


def _split_numbered_alts(text: str) -> list[str]:
    """Split a numbered-list response ("1. ...\\n2. ...") into a list of strings.

    Falls back to returning the whole cleaned text as a single alt if the
    model didn't follow the numbered-list format — Phase 1 would rather
    surface one ugly alt to the user than crash the turn loop on a format
    miss.
    """
    pattern = re.compile(r"^\s*\d+[\.\)]\s*", re.MULTILINE)
    pieces = pattern.split(text)
    alts = [p.strip() for p in pieces if p.strip()]
    return alts if alts else [text.strip()]
