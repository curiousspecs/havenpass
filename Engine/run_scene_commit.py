"""
Arbitration-and-STAGING half of a scene run -- reads the user's picks (made in
chat, not a terminal prompt) from a small JSON file, runs Director arbitration
through the real "director_arbitration" role, and stages the changeset in
DAILIES. Companion to `run_scene_draft.py`; see that file's docstring for why
the turn loop is split in two.

⛔ PHASE 3 (§4 steps 7-8, §7): THIS SCRIPT WRITES NOTHING TO THE BLACKBOARD.
Through Phase 2 the changeset committed straight to the log from here. Now it
sits in `LOGS_scratch_dailies.json` until the user calls the take:

    python run_scene_take.py print    # commit, this take becomes active
    python run_scene_take.py ng       # discard; retained in the ledger for comparison

That is the confirmation point the architecture is built around -- the one a
session "being helpful" is most likely to skip. Nothing here decides it.

Usage:
    python run_scene_commit.py picks.json

picks.json shape: {"Wen": 1, "Ruck": 2, "Klisp": "custom line text"}  -- per
actor, either a 1-indexed choice into LOGS_scratch_draft.json's `alts` list,
or a literal string when the user's actual pick was none of the drafted alts
(the architecture's authorial-control discipline: the user may always write
their own line instead of picking a drafted one -- this is not a fallback,
it is the same authority the numbered choice exercises, in a different form).

The take number is NOT the draft's hardcoded `take: 1`: it is `next_take()`
for the Scene ID at staging time, so re-running the same scene is a proper
reshoot (a new take under the same slate) rather than a second take 1.
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

import director  # noqa: E402
from blackboard import changeset_to_events, marks, next_take  # noqa: E402

LOG_PATH = WORLD_DIR / "blackboard" / "phase3_router_proof_events.jsonl"
DRAFT_IN = ENGINE_DIR / "LOGS_scratch_draft.json"
DAILIES_OUT = ENGINE_DIR / "LOGS_scratch_dailies.json"


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_scene_commit.py picks.json")
        sys.exit(1)
    picks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    draft = json.loads(DRAFT_IN.read_text(encoding="utf-8"))
    scene = dict(draft["scene"])
    all_alts = draft["alts"]

    # Slate: same Scene ID, next unused take number (§7).
    scene["take"] = next_take(LOG_PATH, scene["scene_id"])

    selected_lines: dict[str, str] = {}
    for actor_name, alts in all_alts.items():
        pick = picks[actor_name]
        if isinstance(pick, str):
            selected_lines[actor_name] = pick  # user wrote their own line
        else:
            selected_lines[actor_name] = alts[pick - 1]

    print(f"=== Scene {scene['scene_id']}, take {scene['take']} ===")
    print("=== Selected lines ===")
    for actor_name, line in selected_lines.items():
        print(f"{actor_name}: {line}")

    print("\nAsking the Director to arbitrate the whole scene (director_arbitration role)...")
    result = director.arbitrate_scene(scene, selected_lines)
    verdicts = result["verdicts"]
    changeset = result["changeset"]
    if "read_facts" in draft:
        changeset["read_facts"] = draft["read_facts"]

    print("\n--- Director verdicts ---")
    for actor_name, verdict in verdicts.items():
        print(f"{actor_name}: plausible={verdict['plausible']} -- {verdict['reason']}")

    staged = {
        "scene": scene,
        "selected_lines": selected_lines,
        "verdicts": verdicts,
        "changeset": changeset,
        "events": changeset_to_events(scene, changeset),
        "marks_fact_count": len(marks(LOG_PATH, scene["scene_id"])["social_facts"]),
        "log_path": str(LOG_PATH),
    }
    DAILIES_OUT.write_text(json.dumps(staged, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== DAILIES (staged, NOT committed) ===")
    for etype, payload in staged["events"]:
        print(f"  {etype}: {json.dumps(payload, ensure_ascii=False)}")
    print(f"\nStaged to {DAILIES_OUT}. Nothing written to {LOG_PATH}.")
    print("Call the take:  python run_scene_take.py print   |   python run_scene_take.py ng")


if __name__ == "__main__":
    main()
