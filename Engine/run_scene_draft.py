"""
Non-interactive drafting half of a full router-proof scene run.

The project's working rules name two disciplines that a session is most likely to
violate while "being helpful": nothing commits to the blackboard without a
user confirmation point, and the user keeps a hand on characterization (Actors
draft alts, the user picks -- a session picking "the best one" silently has
removed the authorial control the design was built around). `run_scene.py` is
interactive (input()) for exactly that reason.

This script is the same turn loop's drafting half, split out so the alts can
be surfaced to the user OUTSIDE a blocking terminal prompt -- through chat --
and the picks fed back via `run_scene_commit.py`. It calls the real backends
(no mock, no shortcut) and writes what it drafted to a scratch JSON file for
the commit half to read back.

Writes to Worlds\\Havenpass\\blackboard\\phase3_router_proof_events.jsonl --
a NEW file, separate from phase1_test_events.jsonl and phase2_test_events.jsonl,
so neither earlier phase's already test-gated recording is touched. This is
the first scene played through the `backends/` router end-to-end (the
router was previously proven only by direct role calls, never by a played
scene) -- an engineering proof, not canon.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ENGINE_DIR = Path(__file__).parent
WORLD_DIR = ENGINE_DIR.parent / "Worlds" / "Havenpass"
sys.path.insert(0, str(WORLD_DIR))
sys.path.insert(0, str(ENGINE_DIR))

import actor  # noqa: E402
import director  # noqa: E402
from blackboard import marks, next_take  # noqa: E402
from world_pack import INITIAL_SOCIAL_STATE, PERSONAS  # noqa: E402

LOG_PATH = WORLD_DIR / "blackboard" / "phase3_router_proof_events.jsonl"
DRAFT_OUT = ENGINE_DIR / "LOGS_scratch_draft.json"


def main() -> None:
    ok, report = director.preflight()
    print(report)
    if not ok:
        print("\nRefusing to draft with an unusable backend.")
        sys.exit(1)
    print()

    scene = director.frame_scene()
    # Slate (§7): same Scene ID, next unused take -- re-running this scene is a reshoot.
    scene["take"] = next_take(LOG_PATH, scene["scene_id"])
    actors_present = scene["actors_present"]

    print(f"=== Scene {scene['scene_id']} (take {scene['take']}) ===")
    print(f"Story-time: {scene['story_time']}")
    print(f"Location: {scene['location']}")
    print(f"Actors present: {', '.join(actors_present)}")
    print(f"Writing to: {LOG_PATH}")

    # MARKS (§7), not replay(): the state every Actor is in when THIS scene
    # starts -- earlier scenes' active takes, exclusive of this scene's own
    # prior takes. Through Phase 2 this was replay(), which fed a reshoot its
    # own previous take's facts as background knowledge.
    existing_state = marks(LOG_PATH, scene["scene_id"])
    social_facts = list(INITIAL_SOCIAL_STATE) + existing_state["social_facts"]
    plot_history = list(existing_state["plot_history"])

    briefs = {}
    all_alts = {}
    for actor_name in actors_present:
        persona = PERSONAS[actor_name]
        brief = director.build_actor_brief(actor_name, scene, social_facts, plot_history)
        briefs[actor_name] = brief

        print(f"\n=== {actor_name}'s brief ===")
        print(f"Blocking: {brief['blocking']}")
        print(f"Situation: {brief['situation']}")
        bk = brief["background_knowledge"]
        print("Filtered background knowledge:")
        if bk["social_facts"] or bk["plot_history"]:
            for fact in bk["social_facts"]:
                print(f"  - fact: {fact}")
            for entry in bk["plot_history"]:
                print(f"  - plot history: {entry}")
        else:
            print("  (none)")

        print(f"\nAsking {actor_name} (actor_draft role) to draft alts...")
        alts = actor.draft_alts(persona, brief)
        all_alts[actor_name] = alts
        print(f"--- {actor_name}'s drafted alts ---")
        for i, alt in enumerate(alts, start=1):
            print(f"{i}. {alt}\n")

    # READ side of the causal-link graph (§6): every fact object that reached
    # any Actor's brief this take. continuity.py walks these on a reshoot.
    read_facts = sorted({
        f["object"] for br in briefs.values()
        for f in br["background_knowledge"]["social_facts"] if "object" in f
    })

    out = {
        "scene": scene,
        "read_facts": read_facts,
        "existing_state_at_draft": existing_state,
        "social_facts_seed": social_facts,
        "plot_history_seed": plot_history,
        "alts": all_alts,
    }
    DRAFT_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDrafted alts for all actors written to {DRAFT_OUT}")
    print("Run run_scene_commit.py after picking one alt per actor.")


if __name__ == "__main__":
    main()
