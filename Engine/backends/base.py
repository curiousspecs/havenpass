"""
Backend interface and errors — the one seam every model call goes through.

`Local & Hybrid Hosting Plan.md` §4 specified this at Phase 0 ("a thin router
in the Director config -- one entry per logical role, each pointing at a
backend") and it was never built: actor.py called `ollama.chat` directly and
director.py constructed a Gemini client directly. That is why the 2026-08-17
model change (Gemini key deleted, build moves to Claude) touched engine files
at all. It should have been a config edit.

The contract is deliberately one function. A backend takes a prompt and an
optional system prompt and returns text. Everything model-specific -- think-block
stripping, JSON fence stripping, SDK construction, subprocess plumbing -- lives
behind it, because that is exactly the knowledge the engine should not hold.

⛔ WHAT THIS SEAM IS NOT. It is not a capability check. A backend being
importable does not mean it is reachable, and `available()` is a cheap,
non-authoritative hint used only to render a pre-flight report. The engine's
standing discipline (project rule: "surface the failing precondition *before*
starting") is served by preflight() in routing.py, not by trusting this.
"""

from __future__ import annotations

from typing import Protocol


class BackendError(RuntimeError):
    """Base class for every backend failure the engine should catch by intent."""


class BackendUnavailable(BackendError):
    """The backend cannot be used at all: SDK missing, binary absent, key absent.

    Distinct from BackendCallFailed on purpose. This one is a PRECONDITION
    failure -- it is knowable before a scene starts, and the pre-flight is
    supposed to surface it rather than let a turn loop die halfway through a
    scene with half a changeset written.
    """


class BackendCallFailed(BackendError):
    """The backend was reachable and the call failed anyway.

    Timeouts, refusals, malformed responses, rate limits. Not knowable in
    advance; the caller decides whether to retry, re-route, or abort the take.
    """


class Backend(Protocol):
    """What every adapter must provide. Deliberately small."""

    name: str

    def complete(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        """Return the model's text response, model-specific artifacts removed.

        `model` selects a tier within this backend (the plan's "model-tier
        field" -- e.g. flash vs pro, or a larger local model for an unattended
        drafting pass). None means the backend's configured default.
        """
        ...

    def available(self) -> tuple[bool, str]:
        """(usable, one-line reason). A HINT for pre-flight, never a guarantee."""
        ...
