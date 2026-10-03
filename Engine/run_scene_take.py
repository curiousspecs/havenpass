"""
Take confirmation (§4 step 8, §7) -- the user's call on what sits in dailies.

    python run_scene_take.py print [dailies.json]
    python run_scene_take.py ng    [dailies.json]

`print`: the staged changeset's events commit to the blackboard and the
`take_printed` ledger event makes this take the active one for its Scene ID
(superseding any earlier printed take of the same scene). `ng`: nothing
commits; the Actors and locations are already back to one; the discarded
changeset is retained in a `take_ng` ledger event for comparison and is never
folded into state. Either way the dailies file is consumed (renamed with the
outcome) so the same take cannot be called twice from a stale file -- and
`blackboard.print_take()` / `ng_take()` refuse a re-used take number anyway.

No model is called here. This is bookkeeping the user controls, not judgment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent
sys.path.insert(0, str(ENGINE_DIR))

from blackboard import active_takes, ng_take, print_take, replay  # noqa: E402

DAILIES_DEFAULT = ENGINE_DIR / "LOGS_scratch_dailies.json"


def main() -> None:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("print", "ng"):
        print("usage: run_scene_take.py print|ng [dailies.json]")
        sys.exit(1)
    call = sys.argv[1]
    dailies_path = Path(sys.argv[2]) if len(sys.argv) == 3 else DAILIES_DEFAULT
    if not dailies_path.exists():
        print(f"Nothing in dailies at {dailies_path} -- run run_scene_commit.py first.")
        sys.exit(1)

    staged = json.loads(dailies_path.read_text(encoding="utf-8"))
    scene = staged["scene"]
    log_path = Path(staged["log_path"])
    sid, take = scene["scene_id"], scene["take"]
    events = [(etype, payload) for etype, payload in staged["events"]]

    if call == "print":
        written = print_take(log_path, sid, take, events)
        print(f"PRINTED: scene {sid} take {take} -- {len(written) - 1} content events + take_printed")
    else:
        ng_take(log_path, sid, take, staged["changeset"])
        print(f"NG: scene {sid} take {take} -- nothing committed; changeset retained in the ledger")

    consumed = dailies_path.with_name(dailies_path.stem + f".{call}ed-{sid}-t{take}.json")
    dailies_path.replace(consumed)
    print(f"Dailies consumed -> {consumed.name}")

    print(f"\nActive takes: {active_takes(log_path)}")
    state = replay(log_path)
    state2 = replay(log_path)
    print(f"Replayed state: {len(state['social_facts'])} social facts, "
          f"{len(state['plot_history'])} plot entries, "
          f"memory streams for {sorted(state['memory_streams'])}")
    print("Replay is deterministic: PASS." if state == state2
          else "Replay MISMATCH -- investigate before trusting this log. FAIL.")


if __name__ == "__main__":
    main()
