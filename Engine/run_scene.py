"""
Interactive turn loop -- Phase 2 brief filtering, now with the Phase 3 take gate
(dailies -> print/NG, §4 steps 7-8, §7). Originally (Build Roadmap & Phasing.md, Phase 2):
"Add a second and third Actor in-scene; build the brief-filtering logic
that limits each Actor to what its character would plausibly know."

Test gate: deliberately give one Actor a fact only another should have,
confirm it doesn't leak into the first Actor's brief. (The fully automated
version of this same test lives in director.py's `__main__` self-test --
this script is the live, real-LLM demonstration on top of that.)

Run from the Engine\\ folder with the venv active:
    python run_scene.py

Writes to Worlds\\Havenpass\\blackboard\\phase2_test_events.jsonl -- a new,
separate file from Phase 1's phase1_test_events.jsonl, so Phase 1's already
test-gated recording stays untouched.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads Engine\.env -- backend credentials, whichever backend
               # routing.json points a role at. No vendor is named here any more.

ENGINE_DIR = Path(__file__).parent
WORLD_DIR = ENGINE_DIR.parent / "Worlds" / "Havenpass"
sys.path.insert(0, str(WORLD_DIR))
sys.path.insert(0, str(ENGINE_DIR))

import actor  # noqa: E402
import director  # noqa: E402
from blackboard import changeset_to_events, marks, next_take, ng_take, print_take, replay  # noqa: E402
from world_pack import INITIAL_SOCIAL_STATE, PERSONAS  # noqa: E402

LOG_PATH = WORLD_DIR / "blackboard" / "phase2_test_events.jsonl"


def _prompt_choice(actor_name: str, alts: list[str]) -> str:
    print(f"\n--- {actor_name}'s drafted alts ---")
    for i, alt in enumerate(alts, start=1):
        print(f"{i}. {alt}\n")
    while True:
        choice = input("Pick one [1-{}], or 'r' to redraft: ".format(len(alts))).strip().lower()
        if choice == "r":
            return choice
        if choice.isdigit() and 1 <= int(choice) <= len(alts):
            return choice
        print("Not a valid choice, try again.")


def main() -> None:
    # ⛔ PRE-FLIGHT FIRST, BEFORE ANY SCENE STATE EXISTS (backend router, 2026-08-22).
    # Project rule: "surface the failing precondition *before* starting."
    # The failure this prevents is specific and was previously reachable: the
    # Actors draft fine against the local model, the user reads every alt and
    # picks their lines, and THEN the Director's backend turns out to be
    # unreachable -- leaving a scene half-played, nothing committed, and the
    # user's authorial choices thrown away. A backend that is down should cost
    # a message, not a scene.
    ok, report = director.preflight()
    print(report)
    if not ok:
        print("\nRefusing to start a scene with an unusable backend. Fix the "
              "above, or re-route the role in backends/routing.json.")
        sys.exit(1)
    print()

    scene = director.frame_scene()
    # Slate (§7): same Scene ID, next unused take number -- a re-run is a reshoot.
    scene["take"] = next_take(LOG_PATH, scene["scene_id"])
    actors_present = scene["actors_present"]

    print(f"=== Scene {scene['scene_id']} (take {scene['take']}) ===")
    print(f"Story-time: {scene['story_time']}")
    print(f"Location: {scene['location']}")
    print(f"Actors present: {', '.join(actors_present)}")

    # Replay whatever's already committed to this scene's own log (empty on
    # a first run) and merge it with the World Pack baseline -- this is the
    # full current social-state/plot-history table that gets filtered per
    # actor below, not just the static seed.
    existing_state = marks(LOG_PATH, scene["scene_id"])  # §7: earlier scenes only, never this scene's own prior takes
    social_facts = list(INITIAL_SOCIAL_STATE) + existing_state["social_facts"]
    plot_history = list(existing_state["plot_history"])

    # Step 4 (§4): each Actor drafts independently from its OWN filtered
    # brief. No Actor's prompt ever carries another Actor's persona or
    # brief (§11) -- these calls are kept fully separate in this loop, one
    # at a time, each building its brief fresh from build_actor_brief().
    selected_lines: dict[str, str] = {}
    read_facts: set[str] = set()
    for actor_name in actors_present:
        persona = PERSONAS[actor_name]
        brief = director.build_actor_brief(actor_name, scene, social_facts, plot_history)
        read_facts.update(f["object"] for f in brief["background_knowledge"]["social_facts"] if "object" in f)

        print(f"\n=== {actor_name}'s brief ===")
        print(f"Blocking: {brief['blocking']}")
        print(f"Situation: {brief['situation']}")
        print(f"Filtered background knowledge (this is the brief-filtering "
              f"test gate -- confirm no other actor's restricted facts "
              f"appear here):")
        bk = brief["background_knowledge"]
        if bk["social_facts"] or bk["plot_history"]:
            for fact in bk["social_facts"]:
                print(f"  - fact: {fact}")
            for entry in bk["plot_history"]:
                print(f"  - plot history: {entry}")
        else:
            print("  (none)")

        while True:
            print(f"\nAsking {actor_name} (deepseek-r1:14b) to draft alts...")
            alts = actor.draft_alts(persona, brief)
            choice = _prompt_choice(actor_name, alts)
            if choice != "r":
                break
        selected_lines[actor_name] = alts[int(choice) - 1]

    # Step 6 (§4, §11): one Director arbitration call covering every actor
    # in the scene -- a single structured verdict set, not N regenerated
    # passes.
    print("\nAsking the Director to arbitrate the whole scene...")
    result = director.arbitrate_scene(scene, selected_lines)
    verdicts = result["verdicts"]
    changeset = result["changeset"]
    changeset["read_facts"] = sorted(read_facts)  # the READ side of the causal graph (§6)

    print("\n--- Director verdicts ---")
    any_implausible = False
    for actor_name, verdict in verdicts.items():
        print(f"{actor_name}: plausible={verdict['plausible']} -- {verdict['reason']}")
        if not verdict["plausible"]:
            any_implausible = True

    # Step 7 (§4): stage the changeset in dailies. Step 8: the USER calls the
    # take -- print or NG. Phase 3 replaces Phase 2's "write it straight to the
    # blackboard" with this gate; nothing below reaches the log without it.
    events = changeset_to_events(scene, changeset)
    print("\n=== DAILIES (staged, not committed) ===")
    for etype, payload in events:
        print(f"  {etype}: {payload}")
    if any_implausible:
        print("\nAt least one actor's delivery was flagged as implausible. "
              "There is no bounce-back-to-Actor loop yet; NG reruns the scene "
              "as a new take under the same Scene ID.")
    while True:
        call = input(f"\nCall the take for {scene['scene_id']} take {scene['take']} "
                     "-- [p]rint / [n]g: ").strip().lower()
        if call in ("p", "print"):
            print_take(LOG_PATH, scene["scene_id"], scene["take"], events)
            print(f"\nPRINTED -- committed to {LOG_PATH}")
            break
        if call in ("n", "ng"):
            ng_take(LOG_PATH, scene["scene_id"], scene["take"], changeset)
            print("\nNG -- nothing committed; changeset retained in the ledger. Back to one.")
            return
        print("p or n.")

    # Step 9 stand-in: print every actor's final selected line, then prove
    # replay reproduces state -- this is the actual Phase 2 test gate
    # (live half of it; director.py's __main__ is the automated half).
    print("\n=== Output ===")
    for actor_name in actors_present:
        print(f"{actor_name}: {selected_lines[actor_name]}")

    print("\n=== Replay check ===")
    state = replay(LOG_PATH)
    print(f"Memory streams: {state['memory_streams']}")
    print(f"Social facts: {state['social_facts']}")
    print(f"Plot history: {state['plot_history']}")

    state2 = replay(LOG_PATH)
    if state == state2:
        print("\nReplay is deterministic: re-running replay() on the same "
              "log produced identical state. PASS.")
    else:
        print("\nReplay MISMATCH between two runs -- investigate before "
              "trusting this log. FAIL.")


if __name__ == "__main__":
    main()
