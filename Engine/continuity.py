"""
Continuity Engine, deterministic half (§7 step 3, §8 step 2, §11) -- Phase 3, step 3.

"Anything that looks like 'find every scene affected by this change' is a graph
traversal over structured data, not an LLM scan of the whole plot history. The
LLM is invoked only on the narrowed candidate set, to classify and draft, never
to search." (§11)

THE GRAPH. Every committed scene's plot_history_entry carries two fact lists:
  established_facts -- what this scene made true (fact object ids)
  read_facts        -- what this scene READ: the facts that were in its Actors'
                       briefs at draft time (Phase 3 addition; entries written
                       before it exist have no such field and are treated as
                       UNKNOWN, never as "read nothing")
An edge runs from scene A to scene B when B read a fact A established. That is
the causal-link graph the Director's framing produces as a by-product (§3).

THE WALK. Given a reshoot of scene S with a new changeset, or a World Pack edit
expressed as a set of facts that stop being true:
  1. diff the OLD active take's established facts against the NEW ones ->
     `removed` (true before, not after) and `added`
  2. walk every scene framed AFTER S, in scene order, carrying a frontier of
     invalidated facts that starts as `removed`. A scene that read any fact in
     the frontier is a CANDIDATE, and every fact it established joins the
     frontier -- its establishments rested on something that is no longer true,
     so scenes downstream of it are reached transitively.
  3. a scene whose entry carries no read_facts is reported UNKNOWN-READS: it
     might depend on the change and the record cannot say. It is surfaced,
     never silently scored unaffected, and its establishments do NOT join the
     frontier (an unknown is not evidence of a link either).
  4. everything else is UNAFFECTED.

WHAT THIS DOES NOT DO. Severity (unaffected / minor / major) and patch drafting
are judgment, routed to the `continuity_classify` role on the candidate set
only (§7 step 4). This module never calls a model and never writes to the
blackboard: its output is the conflict REPORT the user reviews before anything
commits (§7 step 5). It is the search; the judgment is elsewhere on purpose.
"""

from __future__ import annotations

from pathlib import Path

from blackboard import CONTENT_EVENTS, read_events, take_ledger

UNKNOWN = "unknown-reads"
CANDIDATE = "candidate"
UNAFFECTED = "unaffected"


# --------------------------------------------------------------------------
# Building the per-scene fact view out of the active takes
# --------------------------------------------------------------------------

def scene_facts(log_path: Path) -> list[dict]:
    """One record per scene, in scene (first-framing) order, from ACTIVE takes only:
    {scene_id, order, take, established: set|None, reads: set|None, has_entry}
    `reads` is None when the active take's plot entry predates read_facts."""
    events = read_events(log_path)
    ledger = take_ledger(events)
    view: dict[str, dict] = {
        sid: {"scene_id": sid, "order": s["order"], "take": s["active"],
              "established": set(), "reads": None, "has_entry": False}
        for sid, s in ledger.items()
    }
    for e in events:
        if e["event_type"] not in CONTENT_EVENTS:
            continue
        rec = view[e["scene_id"]]
        if e["take"] != rec["take"]:
            continue
        p = e["payload"]
        if e["event_type"] == "plot_history_entry":
            rec["has_entry"] = True
            rec["established"].update(p.get("established_facts", []))
            if "read_facts" in p:
                rec["reads"] = set(p["read_facts"]) if rec["reads"] is None else rec["reads"] | set(p["read_facts"])
        elif e["event_type"] == "social_fact_asserted" and "object" in p:
            rec["established"].add(p["object"])
    return sorted(view.values(), key=lambda r: r["order"])


def established_by(log_path: Path, scene_id: str) -> set[str]:
    for rec in scene_facts(log_path):
        if rec["scene_id"] == scene_id:
            return set(rec["established"])
    return set()


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------

def walk(scenes: list[dict], start_order: int, removed: set[str]) -> dict:
    """Pure function over the per-scene view. Returns
    {scene_id: {"status": ..., "via": sorted facts that linked it}} for every
    scene framed after `start_order`. Deterministic: scene order is the only
    order used and sets are reported sorted."""
    frontier = set(removed)
    report: dict[str, dict] = {}
    for rec in scenes:
        if rec["order"] <= start_order:
            continue
        sid = rec["scene_id"]
        if rec["reads"] is None:
            report[sid] = {"status": UNKNOWN, "via": []}
            continue
        hit = rec["reads"] & frontier
        if hit:
            report[sid] = {"status": CANDIDATE, "via": sorted(hit)}
            frontier |= rec["established"]
        else:
            report[sid] = {"status": UNAFFECTED, "via": []}
    return report


def reshoot_report(log_path: Path, scene_id: str, new_established: set[str]) -> dict:
    """Conflict report for reshooting `scene_id` with a take that establishes
    `new_established` (fact object ids), against its current active take.
    Returns {"scene_id", "removed", "added", "scenes": walk(...), "summary"}."""
    scenes = scene_facts(log_path)
    target = next((r for r in scenes if r["scene_id"] == scene_id), None)
    if target is None:
        raise KeyError(f"scene {scene_id!r} is not in {log_path.name}; nothing to reshoot")
    old = set(target["established"])
    new = set(new_established)
    removed, added = old - new, new - old
    scenes_report = walk(scenes, target["order"], removed)
    return {
        "scene_id": scene_id,
        "old_take": target["take"],
        "removed": sorted(removed),
        "added": sorted(added),
        "scenes": scenes_report,
        "summary": _summary(scenes_report),
    }


def world_pack_edit_report(log_path: Path, facts_no_longer_true: set[str]) -> dict:
    """§8 step 2: the same walk with no target scene -- every committed scene is
    downstream of a World Pack fact, so the walk starts before scene 0."""
    scenes = scene_facts(log_path)
    scenes_report = walk(scenes, -1, set(facts_no_longer_true))
    return {"removed": sorted(facts_no_longer_true), "scenes": scenes_report,
            "summary": _summary(scenes_report)}


def _summary(scenes_report: dict) -> dict:
    out = {CANDIDATE: 0, UNAFFECTED: 0, UNKNOWN: 0}
    for v in scenes_report.values():
        out[v["status"]] += 1
    return out


def format_report(report: dict) -> str:
    lines = []
    if "scene_id" in report:
        lines.append(f"Reshoot of {report['scene_id']} (active take {report['old_take']})")
    lines.append(f"  facts no longer established: {report['removed'] or '(none)'}")
    if "added" in report:
        lines.append(f"  facts newly established:     {report['added'] or '(none)'}")
    s = report["summary"]
    lines.append(f"  later scenes: {s[CANDIDATE]} candidate / {s[UNAFFECTED]} unaffected / {s[UNKNOWN]} unknown-reads")
    for sid, v in report["scenes"].items():
        via = f"  via {v['via']}" if v["via"] else ""
        lines.append(f"    {sid}: {v['status']}{via}")
    if s[CANDIDATE]:
        lines.append("  -> candidates go to the continuity_classify role for minor/major; nothing commits until the user approves.")
    if s[UNKNOWN]:
        lines.append("  -> unknown-reads scenes predate read_facts; the record cannot say. Surfaced, not scored.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Self-test -- synthetic scene histories, no LLM, per the roadmap's Phase 3 gate:
# "unit-test the graph traversal against synthetic scene histories before
#  trusting it on a real reshoot"
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    from blackboard import changeset_to_events, print_take

    def cs(facts: list[str], reads: list[str] | None) -> dict:
        c = {"memory_entries": {"Wen": "m"},
             "social_facts": [{"subject": "Wen", "predicate": "knows", "object": o} for o in facts],
             "plot_summary": "s"}
        if reads is not None:
            c["read_facts"] = reads
        return c

    def shoot(log: Path, sid: str, take: int, facts: list[str], reads: list[str] | None):
        scene = {"scene_id": sid, "take": take, "story_time": "t"}
        print_take(log, sid, take, changeset_to_events(scene, cs(facts, reads)))

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "events.jsonl"
        # History:  A establishes a,b   B reads a -> establishes c   C reads c -> establishes d
        #           D reads b            E reads nothing              F (legacy entry, no read_facts)
        shoot(log, "A", 1, ["a", "b"], [])
        shoot(log, "B", 1, ["c"], ["a"])
        shoot(log, "C", 1, ["d"], ["c"])
        shoot(log, "D", 1, [], ["b"])
        shoot(log, "E", 1, ["e"], [])
        shoot(log, "F", 1, ["f"], None)

        view = {r["scene_id"]: r for r in scene_facts(log)}
        assert view["A"]["established"] == {"a", "b"} and view["B"]["reads"] == {"a"}
        assert view["F"]["reads"] is None
        print("  1. per-scene fact view built from active takes")

        # 1. Reshoot A dropping `a`, keeping `b`: B (read a) and C (read c, which B
        #    established) are candidates; D (read b) and E are unaffected; F unknown.
        r = reshoot_report(log, "A", {"b"})
        assert r["removed"] == ["a"] and r["added"] == []
        assert r["scenes"]["B"] == {"status": CANDIDATE, "via": ["a"]}
        assert r["scenes"]["C"] == {"status": CANDIDATE, "via": ["c"]}, r["scenes"]["C"]
        assert r["scenes"]["D"]["status"] == UNAFFECTED
        assert r["scenes"]["E"]["status"] == UNAFFECTED
        assert r["scenes"]["F"]["status"] == UNKNOWN
        assert r["summary"] == {CANDIDATE: 2, UNAFFECTED: 2, UNKNOWN: 1}
        print("  2. removing a fact reaches direct AND transitive dependants, and only them")

        # 2. Reshoot A keeping both facts and adding one: nothing removed -> nothing affected.
        r = reshoot_report(log, "A", {"a", "b", "z"})
        assert r["removed"] == [] and r["added"] == ["z"]
        assert all(v["status"] in (UNAFFECTED, UNKNOWN) for v in r["scenes"].values())
        print("  3. a reshoot that removes nothing affects nothing (additions are not conflicts)")

        # 3. Reshoot B dropping `c`: only C is downstream; A is upstream and never reported.
        r = reshoot_report(log, "B", set())
        assert "A" not in r["scenes"] and r["scenes"]["C"]["status"] == CANDIDATE
        assert r["scenes"]["D"]["status"] == UNAFFECTED
        print("  4. the walk only runs forward from the reshot scene")

        # 4. World Pack edit invalidating `b`: D is a candidate from scene 0 onward.
        r = world_pack_edit_report(log, {"b"})
        assert r["scenes"]["D"]["status"] == CANDIDATE and r["scenes"]["A"]["status"] == UNAFFECTED
        print("  5. a World Pack edit walks the whole history")

        # 5. Unknown reads never propagate: reshoot E dropping `e` -- F comes after E,
        #    is unknown, and its establishment `f` must NOT be treated as invalidated.
        shoot(log, "G", 1, [], ["f"])
        r = reshoot_report(log, "E", set())
        assert r["scenes"]["F"]["status"] == UNKNOWN and r["scenes"]["G"]["status"] == UNAFFECTED
        print("  6. an unknown-reads scene is surfaced but does not spread invalidation")

        # 6. The walk respects ACTIVE takes: reshoot B for real (print take 2 without c),
        #    then a report on A must see B's take 2 (reads a, establishes nothing).
        shoot(log, "B", 2, [], ["a"])
        view = {r["scene_id"]: r for r in scene_facts(log)}
        assert view["B"]["take"] == 2 and view["B"]["established"] == set()
        r = reshoot_report(log, "A", {"b"})
        assert r["scenes"]["B"]["status"] == CANDIDATE and r["scenes"]["C"]["status"] == UNAFFECTED
        print("  7. the graph is built from active takes, so a printed reshoot changes later walks")

        # 7. Determinism and the human-readable form.
        assert reshoot_report(log, "A", {"b"}) == reshoot_report(log, "A", {"b"})
        text = format_report(reshoot_report(log, "A", {"b"}))
        assert "candidate" in text and "unknown-reads" in text
        print("  8. reports are deterministic and render")

        try:
            reshoot_report(log, "NOPE", set())
            raise AssertionError("unknown scene accepted")
        except KeyError:
            pass
        print("  9. reshooting a scene that was never shot is refused")

    print("continuity.py self-test: PASS")
