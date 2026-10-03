"""
Blackboard: the event-sourced store described in the architecture doc (§6),
now carrying the Take Ledger (§7) -- Phase 3, step 1 (Build Roadmap & Phasing.md).

WHAT CHANGED FROM PHASES 1-2, and why the old logs still replay identically
--------------------------------------------------------------------------
Phases 1-2 wrote every content event straight to the log with `take: 1` and
never branched on it. Phase 3 adds two LEDGER events and makes replay branch:

  take_printed  {scene_id, take}             -> this take is now the ACTIVE
                                                take for its Scene ID; any
                                                earlier printed take is
                                                superseded (excluded from
                                                replay, retained in the file)
  take_ng       {scene_id, take, changeset}  -> the take was discarded in
                                                dailies. The changeset is
                                                RETAINED here for comparison
                                                (§6: "discarded takes are
                                                retained by default") and is
                                                NEVER folded into state.

A content event (memory_appended / social_fact_asserted / plot_history_entry)
folds into state only if its {scene_id, take} is the ACTIVE take of that scene.
Content written for a take that was never printed is inert: `print_take()`
writes the content events FIRST and `take_printed` LAST, so a crash between
the two leaves an unprinted take that replay ignores -- the commit is atomic
against partial writes by construction.

LEGACY RULE. A scene with NO ledger events at all (every log written before
this file existed) has exactly one take in the file, and that take is treated
as active -- so phase1/phase2/phase3 logs replay byte-for-byte as before
(regression-tested in `__main__` against the real files, not assumed). A
scene with no ledger events and MORE than one take is ambiguous and replay
refuses it rather than guessing.

MARKS (§7). `marks(log, scene_id)` = the replay of every EARLIER scene's
active take, exclusive of the named scene. "Earlier" means framed earlier --
scene order is the order Scene IDs FIRST appear in the log -- not "earlier
in the file": a reshoot of scene 1 appended after scene 2 was shot still
counts as before scene 2. A Scene ID not yet in the log is being framed for
the first time, so its marks are the full current state.

"Current state" is still always a fold of events; there is no snapshot
format. Nothing here calls a model.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

LEDGER_EVENTS = frozenset({"take_printed", "take_ng"})
CONTENT_EVENTS = frozenset({"memory_appended", "social_fact_asserted", "plot_history_entry"})


# --------------------------------------------------------------------------
# Raw log I/O
# --------------------------------------------------------------------------

def append_event(log_path: Path, event_type: str, payload: dict) -> dict:
    """Append one event to the JSONL log and return the full event record.

    The envelope (event_id, committed_at, scene_id, take, event_type) wraps
    a payload dict whose shape depends on event_type. Low-level: callers that
    are committing a scene should go through `print_take()` / `ng_take()`,
    which write the ledger event that makes content visible to replay.
    """
    if event_type not in CONTENT_EVENTS and event_type not in LEDGER_EVENTS:
        raise ValueError(f"append_event(): unknown event_type {event_type!r}")
    event = {
        "event_id": str(uuid.uuid4()),
        "committed_at": datetime.now(timezone.utc).isoformat(),
        "scene_id": payload.get("scene_id"),
        "take": payload.get("take", 1),
        "event_type": event_type,
        "payload": payload,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(log_path: Path) -> list[dict]:
    """Every event in commit (file) order. Missing file -> empty list."""
    if not log_path.exists():
        return []
    events = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


# --------------------------------------------------------------------------
# Take Ledger (§7)
# --------------------------------------------------------------------------

def take_ledger(events: list[dict]) -> dict:
    """Fold the ledger view out of an event list.

    Returns {scene_id: {"order": int, "takes": {take: status}, "active": take|None,
    "legacy": bool}} where status is "printed" | "ng" | "unprinted" and `order`
    is the scene's first-appearance rank (0-based) -- the scene ORDER that
    `marks()` uses. `active` is the last printed take; for a legacy scene
    (no ledger events) it is the single take present.
    """
    ledger: dict[str, dict] = {}

    def scene(sid: str) -> dict:
        if sid not in ledger:
            ledger[sid] = {"order": len(ledger), "takes": {}, "active": None, "legacy": True}
        return ledger[sid]

    for e in events:
        etype = e["event_type"]
        sid = e["scene_id"]
        take = e["take"]
        if sid is None:
            raise ValueError(f"event {e.get('event_id')} carries no scene_id")
        s = scene(sid)
        if etype == "take_printed":
            s["legacy"] = False
            s["takes"][take] = "printed"
            s["active"] = take
        elif etype == "take_ng":
            s["legacy"] = False
            s["takes"][take] = "ng"
        elif etype in CONTENT_EVENTS:
            s["takes"].setdefault(take, "unprinted")
        else:
            raise ValueError(f"take_ledger(): unknown event_type {etype!r}")

    for sid, s in ledger.items():
        if s["legacy"]:
            if len(s["takes"]) == 1:
                s["active"] = next(iter(s["takes"]))
            elif len(s["takes"]) > 1:
                raise ValueError(
                    f"scene {sid!r} has takes {sorted(s['takes'])} and no ledger "
                    f"events -- which is active is ambiguous; print one explicitly"
                )
    return ledger


def active_takes(log_path: Path) -> dict[str, int | None]:
    """{scene_id: active take} for every scene in the log."""
    return {sid: s["active"] for sid, s in take_ledger(read_events(log_path)).items()}


def next_take(log_path: Path, scene_id: str) -> int:
    """The take number a fresh attempt at this Scene ID should carry: one past
    the highest take the ledger has seen (printed, NG'd or unprinted), or 1."""
    ledger = take_ledger(read_events(log_path))
    if scene_id not in ledger or not ledger[scene_id]["takes"]:
        return 1
    return max(ledger[scene_id]["takes"]) + 1


# --------------------------------------------------------------------------
# Replay / marks
# --------------------------------------------------------------------------

def _fold(state: dict, event: dict) -> None:
    etype = event["event_type"]
    payload = event["payload"]
    if etype == "memory_appended":
        state["memory_streams"].setdefault(payload["actor"], []).append(payload)
    elif etype == "social_fact_asserted":
        state["social_facts"].append(payload)
    elif etype == "plot_history_entry":
        state["plot_history"].append(payload)
    else:
        raise ValueError(f"replay(): unknown event_type {etype!r}")


def replay(log_path: Path, up_to_scene: str | None = None) -> dict:
    """Fold the ACTIVE take of every scene into current state, in commit order.

    Returns a dict with three top-level structures, matching §6:
      - memory_streams: {actor_name: [entry, ...]}
      - social_facts: [fact, ...]               (social-state table, §6)
      - plot_history: [entry, ...]

    `up_to_scene`: stop before that scene -- i.e. return its MARKS (§7).
    Scenes are ordered by first appearance in the log; every scene that was
    framed before `up_to_scene` contributes its active take, the named scene
    and everything framed after it contribute nothing. A Scene ID absent from
    the log is being framed now, so its marks are the whole current state.
    """
    state = {"memory_streams": {}, "social_facts": [], "plot_history": []}
    events = read_events(log_path)
    if not events:
        return state
    ledger = take_ledger(events)

    cutoff = None
    if up_to_scene is not None and up_to_scene in ledger:
        cutoff = ledger[up_to_scene]["order"]

    for e in events:
        if e["event_type"] in LEDGER_EVENTS:
            continue
        s = ledger[e["scene_id"]]
        if cutoff is not None and s["order"] >= cutoff:
            continue
        if s["active"] != e["take"]:
            continue
        _fold(state, e)
    return state


def marks(log_path: Path, scene_id: str) -> dict:
    """The state every Actor and location is in at the moment `scene_id`
    starts (§7): replay of all earlier scenes' active takes, exclusive."""
    return replay(log_path, up_to_scene=scene_id)


# --------------------------------------------------------------------------
# Dailies -> print / NG (§4 steps 7-8, §7)
# --------------------------------------------------------------------------

def changeset_to_events(scene: dict, changeset: dict) -> list[tuple[str, dict]]:
    """Turn a Director changeset ({memory_entries, social_facts, plot_summary,
    optional read_facts}) into the ordered (event_type, payload) list a take
    commits. One place for this conversion -- run_scene.py and
    run_scene_commit.py used to carry two copies of it.

    `read_facts` (Phase 3): the fact object ids that were in the Actors'
    briefs when this take was drafted -- the READ side of the causal-link
    graph the Continuity Engine walks (§6, §7). Recorded on the plot entry
    when present; absent on entries written before it existed, which
    `continuity.py` reports as unknown rather than as "read nothing"."""
    sid, take, st = scene["scene_id"], scene["take"], scene["story_time"]
    events: list[tuple[str, dict]] = []
    for actor_name, memory_text in changeset["memory_entries"].items():
        events.append(("memory_appended", {
            "scene_id": sid, "take": take, "actor": actor_name, "story_time": st,
            "narrative_sequence_index": 0, "content": memory_text,
        }))
    for fact in changeset["social_facts"]:
        events.append(("social_fact_asserted", {
            "scene_id": sid, "take": take, "story_time": st, **fact,
        }))
    entry = {
        "scene_id": sid, "take": take, "story_time": st, "narrative_sequence_index": 0,
        "summary": changeset["plot_summary"],
        "established_facts": [f["object"] for f in changeset["social_facts"]],
    }
    if "read_facts" in changeset:
        entry["read_facts"] = sorted(set(changeset["read_facts"]))
    events.append(("plot_history_entry", entry))
    return events


def _check_take_unused(log_path: Path, scene_id: str, take: int) -> None:
    ledger = take_ledger(read_events(log_path))
    status = ledger.get(scene_id, {}).get("takes", {}).get(take)
    if status in ("printed", "ng"):
        raise ValueError(
            f"scene {scene_id!r} take {take} is already {status}; a slate number "
            f"is used once -- call next_take() for a fresh attempt"
        )


def print_take(log_path: Path, scene_id: str, take: int,
               events: list[tuple[str, dict]]) -> list[dict]:
    """PRINT a staged changeset (§7): commit its content events, then the
    `take_printed` ledger event that makes them the active take. The ledger
    event goes LAST so a partial write leaves an inert, unprinted take.
    Returns the written event records (ledger event included)."""
    _check_take_unused(log_path, scene_id, take)
    for etype, payload in events:
        if etype not in CONTENT_EVENTS:
            raise ValueError(f"print_take(): {etype!r} is not a content event")
        if payload.get("scene_id") != scene_id or payload.get("take", 1) != take:
            raise ValueError(
                f"print_take(): event slate {payload.get('scene_id')!r}/{payload.get('take')} "
                f"does not match {scene_id!r}/{take}"
            )
    written = [append_event(log_path, etype, payload) for etype, payload in events]
    written.append(append_event(log_path, "take_printed", {"scene_id": scene_id, "take": take}))
    return written


def ng_take(log_path: Path, scene_id: str, take: int, changeset: dict) -> dict:
    """NG a staged changeset (§7): nothing commits to state -- Actors and
    locations are already back to one. The discarded changeset is RETAINED
    in the ledger event for later comparison; replay never folds it."""
    _check_take_unused(log_path, scene_id, take)
    return append_event(log_path, "take_ng",
                        {"scene_id": scene_id, "take": take, "changeset": changeset})


# --------------------------------------------------------------------------
# Self-test -- deterministic, no LLM, per the roadmap's testing split
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    def _cs(tag: str, facts: list[str]) -> dict:
        return {
            "memory_entries": {"Wen": f"Wen remembers {tag}."},
            "social_facts": [{"subject": "Wen", "predicate": "knows", "object": o} for o in facts],
            "plot_summary": f"Summary {tag}.",
        }

    def _scene(sid: str, take: int) -> dict:
        return {"scene_id": sid, "take": take, "story_time": "Day 1, morning"}

    def _facts(state: dict) -> list[str]:
        return [f["object"] for f in state["social_facts"]]

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "events.jsonl"

        # 1. Phase 1 shape, untouched: raw appends with no ledger = legacy scene,
        #    single take treated as active.
        append_event(p, "memory_appended", {
            "scene_id": "S1", "take": 1, "actor": "Wen",
            "story_time": "Day 1, morning", "narrative_sequence_index": 0,
            "content": "Noticed the catalog entry didn't match the object.",
        })
        append_event(p, "social_fact_asserted", {
            "scene_id": "S1", "take": 1,
            "subject": "Wen", "predicate": "knows", "object": "catalog_discrepancy",
            "story_time": "Day 1, morning",
        })
        append_event(p, "plot_history_entry", {
            "scene_id": "S1", "take": 1, "story_time": "Day 1, morning",
            "narrative_sequence_index": 0,
            "summary": "Wen finds a mismatch in the library's catalog records.",
            "established_facts": ["catalog_discrepancy"],
        })
        state = replay(p)
        assert _facts(state) == ["catalog_discrepancy"]
        assert take_ledger(read_events(p))["S1"] == {
            "order": 0, "takes": {1: "unprinted"}, "active": 1, "legacy": True}
        assert replay(p) == state, "replay is not deterministic"
        print("  1. legacy log (no ledger) replays as Phase 1 did")

        # 2. Marks of a scene not yet in the log = full current state.
        assert marks(p, "S2") == state
        assert next_take(p, "S2") == 1
        print("  2. marks() of an unframed scene is the whole current state")

        # 3. Print S2 take 1 through the dailies path.
        print_take(p, "S2", 1, changeset_to_events(_scene("S2", 1), _cs("s2t1", ["gate_locked"])))
        state = replay(p)
        assert _facts(state) == ["catalog_discrepancy", "gate_locked"]
        assert active_takes(p) == {"S1": 1, "S2": 1}
        print("  3. print_take() commits content and makes the take active")

        # 4. Marks of S2 exclude S2's own events and include S1.
        assert _facts(marks(p, "S2")) == ["catalog_discrepancy"]
        assert marks(p, "S1") == {"memory_streams": {}, "social_facts": [], "plot_history": []}
        print("  4. marks() is exclusive and honours scene order")

        # 5. NG a reshoot of S2: state unchanged, changeset retained, never folded.
        t = next_take(p, "S2")
        assert t == 2
        ng_take(p, "S2", t, _cs("s2t2-bad", ["gate_open"]))
        assert _facts(replay(p)) == ["catalog_discrepancy", "gate_locked"]
        led = take_ledger(read_events(p))["S2"]
        assert led["takes"] == {1: "printed", 2: "ng"} and led["active"] == 1
        retained = [e for e in read_events(p) if e["event_type"] == "take_ng"][0]
        assert retained["payload"]["changeset"]["social_facts"][0]["object"] == "gate_open"
        print("  5. ng_take() writes nothing to state and retains the changeset")

        # 6. A slate number is used once.
        try:
            ng_take(p, "S2", 2, _cs("again", []))
            raise AssertionError("re-used take number was accepted")
        except ValueError:
            pass
        print("  6. a printed or NG'd take number is refused a second time")

        # 7. Partial write: content for take 3 with no take_printed is inert.
        for etype, payload in changeset_to_events(_scene("S2", 3), _cs("s2t3-partial", ["gate_smashed"])):
            append_event(p, etype, payload)
        assert _facts(replay(p)) == ["catalog_discrepancy", "gate_locked"]
        assert take_ledger(read_events(p))["S2"]["takes"][3] == "unprinted"
        print("  7. content without a take_printed event does not fold (crash-safe commit)")

        # 8. Reshoot S1 AFTER S2 exists: take 2 printed supersedes the legacy take 1,
        #    and S2's marks now reflect S1's NEW take even though it sits later in the file.
        print_take(p, "S1", 2, changeset_to_events(_scene("S1", 2), _cs("s1t2", ["catalog_forged"])))
        assert active_takes(p)["S1"] == 2
        assert _facts(replay(p)) == ["gate_locked", "catalog_forged"] or \
               _facts(replay(p)) == ["catalog_forged", "gate_locked"]
        assert "catalog_discrepancy" not in _facts(replay(p)), "superseded take still folds"
        assert _facts(marks(p, "S2")) == ["catalog_forged"]
        assert list(replay(p)["memory_streams"]["Wen"])[-1]["content"] == "Wen remembers s1t2."
        print("  8. a later reshoot supersedes the old take and feeds later scenes' marks")

        # 9. Determinism after all of the above.
        assert replay(p) == replay(p) and marks(p, "S2") == marks(p, "S2")
        print("  9. replay and marks are deterministic")

        # 10. Ambiguity is refused, not guessed.
        q = Path(tmp) / "ambiguous.jsonl"
        for t in (1, 2):
            append_event(q, "plot_history_entry", {
                "scene_id": "X", "take": t, "story_time": "t", "narrative_sequence_index": 0,
                "summary": "s", "established_facts": []})
        try:
            replay(q)
            raise AssertionError("two unledgered takes were replayed")
        except ValueError:
            pass
        print(" 10. two takes with no ledger event is refused as ambiguous")

    # 11. REGRESSION against the real Phase 1/2/3 logs, if they are reachable:
    #     every one is a legacy log and must replay exactly as it did before
    #     the ledger existed. Compared to a baseline the test writes on first
    #     run beside the logs? No -- a baseline file would be a second source
    #     of truth. Instead: the legacy rule is exercised by asserting every
    #     real scene is single-take with `active == that take`, and replay()
    #     agrees with a plain fold that ignores takes entirely.
    world = Path(__file__).parent.parent / "Worlds" / "Havenpass" / "blackboard"
    checked = 0
    for logf in sorted(world.glob("*.jsonl")) if world.exists() else []:
        evs = read_events(logf)
        plain = {"memory_streams": {}, "social_facts": [], "plot_history": []}
        for e in evs:
            if e["event_type"] in CONTENT_EVENTS:
                _fold(plain, e)
        if all(e["event_type"] in CONTENT_EVENTS for e in evs):
            assert replay(logf) == plain, f"{logf.name}: replay differs from the pre-ledger fold"
            checked += 1
    print(f" 11. regression: {checked} real pre-ledger log(s) replay unchanged")

    print("blackboard.py self-test: PASS")
