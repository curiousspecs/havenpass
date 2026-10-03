"""
Backend reachability test -- now ROLE-based, through the router.

    py -3.11 -m venv .venv && .venv\\Scripts\\activate
    python test_backends.py            # every role in routing.json
    python test_backends.py --live     # ...and actually spend one call per backend

## What changed, 2026-08-22 (backend router)

This file used to hardcode two vendors -- `test_ollama()` and `test_gemini()`,
each naming a model id and building its own client. That made it a duplicate of
the engine's wiring rather than a test of it: when the model position changed on
2026-08-17, this file and the two engine files all had to be edited, and they
could disagree.

**It now tests what the engine actually does.** It reads `backends/routing.json`,
resolves every declared role, and reports per role. Add a role or repoint one and
this test follows automatically -- there is nothing here to keep in sync.

## The distinction this test refuses to blur

`--live` exists because **a passing pre-flight is not a passing call.** The
default run checks preconditions: SDK importable, service answering, binary on
PATH, key present. That is genuinely useful and genuinely not proof. A clean exit
code is not evidence of anything -- so when you need evidence, spend the call and
read the string that comes back.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()  # reads Engine\.env -- whatever credentials the routed backends need

import backends  # noqa: E402  (after load_dotenv: adapters read env at call time)

PROBE = "Reply with exactly: BACKEND OK"
PROBE_SYSTEM = "You reply with exactly what is asked, and nothing else."


def preflight_report() -> bool:
    ok, report = backends.preflight()
    print(report)
    return ok


def live_probe() -> bool:
    """Spend one real call per DISTINCT backend, not per role.

    Per backend rather than per role because the roles sharing a backend share
    its reachability -- five calls to prove one connection is a waste of the
    local model's wall-clock and of tokens on the cloud tier.
    """
    routing = backends.load_routing()
    seen: dict[str, str] = {}
    for role in backends.roles(routing):
        try:
            impl, tier = backends.resolve(role, routing=routing)
        except backends.BackendError as exc:
            print(f"\n--- {role} --- UNROUTABLE: {exc}")
            seen[role] = "unroutable"
            continue
        key = f"{impl.name}/{tier or 'default'}"
        if key in seen:
            continue
        print(f"\n--- {key} (via role {role}) ---")
        try:
            text = impl.complete(PROBE, system=PROBE_SYSTEM, model=tier)
        except backends.BackendError as exc:
            print(f"FAIL: {exc}")
            seen[key] = "fail"
            continue
        print(f"Response: {text[:200]}")
        seen[key] = "pass"
    return all(v == "pass" for v in seen.values()) and bool(seen)


if __name__ == "__main__":
    live = "--live" in sys.argv

    ok = preflight_report()

    if not live:
        print("\n(pre-flight only -- preconditions checked, no call spent. "
              "Run with --live to prove a backend actually answers.)")
        sys.exit(0 if ok else 1)

    if not ok:
        print("\nPre-flight failed above. Probing live anyway so the failure "
              "reports as a real error rather than as a guess.")

    live_ok = live_probe()
    print("\n=== Result ===")
    print(f"pre-flight: {'PASS' if ok else 'FAIL'}")
    print(f"live calls: {'PASS' if live_ok else 'FAIL'}")
    sys.exit(0 if (ok and live_ok) else 1)
