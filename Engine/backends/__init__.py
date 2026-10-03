"""
The backend router -- one seam for every model call in the engine.

Specified in `Local & Hybrid Hosting Plan.md` §4 at Phase 0 and never built,
which is why the 2026-08-17 model change had to edit engine files at all.
Built 2026-08-22.

## The whole public surface

    from backends import complete, preflight, resolve

    text = complete("director_arbitration", prompt, system=...)   # by ROLE
    ok, report = preflight("actor_draft", "director_arbitration")

**The engine names a ROLE. It never names a model or a vendor.** That is the
entire discipline this package enforces: `actor.py` asks for `actor_draft` and
does not know or care that Ollama answered; `director.py` asks for
`director_arbitration` and does not know a `claude` subprocess answered.
Swapping either is an edit to `routing.json`.

## Overrides, in precedence order (§4: "overridable per-scene")

1. per-call kwargs to `complete(...)` -- `backend=`, `model=`
2. env `HAVENPASS_ROUTE_<ROLE>` = "backend" or "backend:model"
3. env `HAVENPASS_ROUTING` = path to an alternative routing.json
4. `backends/routing.json`

Per-scene override is (1): a scene dict carries a `routing` block and
run_scene passes it through, with no engine file changing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .base import Backend, BackendCallFailed, BackendError, BackendUnavailable
from .claude_code_backend import ClaudeCodeBackend
from .gemini_backend import GeminiBackend
from .ollama_backend import OllamaBackend

__all__ = [
    "complete",
    "preflight",
    "resolve",
    "roles",
    "load_routing",
    "Backend",
    "BackendError",
    "BackendUnavailable",
    "BackendCallFailed",
]

_ADAPTERS = {
    "ollama": OllamaBackend,
    "claude_code": ClaudeCodeBackend,
    "gemini": GeminiBackend,
}

_DEFAULT_ROUTING = Path(__file__).with_name("routing.json")


def load_routing(path=None) -> dict:
    """Read the routing table. `HAVENPASS_ROUTING` overrides the default path."""
    p = Path(path or os.environ.get("HAVENPASS_ROUTING") or _DEFAULT_ROUTING)
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise BackendError(
            f"routing table not found at {p}. The engine routes by ROLE and has no "
            "hardcoded fallback model -- that fallback is the thing this package "
            "exists to delete."
        ) from exc
    except json.JSONDecodeError as exc:
        raise BackendError(f"routing table at {p} is not valid JSON: {exc}") from exc


def roles(routing: dict | None = None) -> list[str]:
    return sorted((routing or load_routing()).get("roles", {}))


def resolve(role: str, *, backend: str | None = None, model: str | None = None,
            routing: dict | None = None):
    """Return (backend instance, model tier) for a role, applying overrides.

    Raises BackendError for an unknown role rather than guessing. A typo in a
    role name must not silently route a scene to a default -- a wrong model
    quietly answering is worse than a crash, and much harder to find later.
    """
    routing = routing or load_routing()
    table = routing.get("roles", {})
    if role not in table:
        raise BackendError(
            f"unknown role {role!r}. Known roles: {', '.join(sorted(table)) or 'none'}. "
            "Add it to routing.json rather than hardcoding a backend at the call site."
        )
    entry = dict(table[role])

    env = os.environ.get("HAVENPASS_ROUTE_" + role.upper())
    if env:
        env_backend, _, env_model = env.partition(":")
        entry["backend"] = env_backend.strip()
        if env_model.strip():
            entry["model"] = env_model.strip()

    if backend:
        entry["backend"] = backend
        entry.pop("model", None)  # a backend override invalidates the previous tier
    if model:
        entry["model"] = model

    name = entry.get("backend")
    if name not in _ADAPTERS:
        raise BackendError(
            f"role {role!r} points at backend {name!r}, which has no adapter. "
            f"Available: {', '.join(sorted(_ADAPTERS))}."
        )
    config = {k: v for k, v in routing.get("backends", {}).get(name, {}).items()
              if not k.startswith("_")}
    return _ADAPTERS[name](**config), entry.get("model")


def complete(role: str, prompt: str, *, system: str | None = None,
             backend: str | None = None, model: str | None = None,
             routing: dict | None = None) -> str:
    """Run one completion for a logical ROLE. The engine's only model call."""
    impl, tier = resolve(role, backend=backend, model=model, routing=routing)
    return impl.complete(prompt, system=system, model=tier)


def preflight(*role_names: str, routing: dict | None = None):
    """Check every backend a set of roles depends on, BEFORE a scene starts.

    ⛔ This is the mechanical form of the standing discipline in the project's
    working rules -- "surface the failing precondition *before* starting" -- and of the
    environment caveat that used to be a paragraph of prose asking a session to
    remember to check the Gemini key by hand. Prose does not run.

    Returns (all_ok, report). `available()` is a HINT: True means the
    preconditions checked out, NOT that the next call will succeed.
    """
    routing = routing or load_routing()
    names = role_names or tuple(roles(routing))
    lines = []
    ok_all = True
    seen = {}
    for role in names:
        try:
            impl, tier = resolve(role, routing=routing)
        except BackendError as exc:
            ok_all = False
            lines.append(f"  {role:<22} UNROUTABLE  {exc}")
            continue
        key = (impl.name, getattr(impl, "model", None))
        if key not in seen:
            seen[key] = impl.available()
        ok, reason = seen[key]
        ok_all = ok_all and ok
        mark = "ok  " if ok else "FAIL"
        tier_s = "/" + tier if tier else ""
        lines.append(f"  {role:<22} {mark} {impl.name}{tier_s}  {reason}")
    header = ("backend pre-flight: ALL ROLES USABLE" if ok_all
              else "backend pre-flight: NOT ALL ROLES USABLE")
    return ok_all, header + "\n" + "\n".join(lines)
