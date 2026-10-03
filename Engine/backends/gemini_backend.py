"""
Gemini adapter -- DORMANT, not removed (`Local & Hybrid Hosting Plan.md` §4).

The key was deleted 2026-08-17 on Matt's instruction and he is revoking it at
the provider. This path stays because **model-agnostic means a backend can be
absent without breaking the engine** -- deleting a working backend is not the
same thing as making it optional. Lifted verbatim in behaviour from
director.py's _gemini_client(), which is where this logic used to live.

Both failure modes stay explicit and separate: a missing SDK and a missing key
are different problems and must not report as the same one.
"""

from __future__ import annotations

import os

from .base import BackendCallFailed, BackendUnavailable

DEFAULT_MODEL = "gemini-2.5-flash"  # Pro is a per-call override, not a default:
                                    # Flash's free-tier RPM is roughly double Pro's


class GeminiBackend:
    name = "gemini"

    def __init__(self, model: str = DEFAULT_MODEL, **_ignored):
        self.model = model

    def _client(self):
        try:
            from google import genai
        except ImportError as exc:
            raise BackendUnavailable(
                "the Gemini backend is not installed in this environment "
                "(pip install google-genai). It is intentionally absent from the "
                "2026-08-17 rebuild."
            ) from exc
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key or api_key.startswith("REPLACE-WITH"):
            raise BackendUnavailable(
                "GEMINI_API_KEY is missing or a placeholder. The key was DELETED "
                "2026-08-17 on Matt's instruction and revoked at the provider; this "
                "backend is dormant by design, not broken."
            )
        return genai.Client(api_key=api_key)

    def complete(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        client = self._client()
        contents = f"{system}\n\n{prompt}" if system else prompt
        try:
            response = client.models.generate_content(
                model=model or self.model, contents=contents
            )
        except Exception as exc:
            raise BackendCallFailed(f"Gemini generate_content failed: {exc}") from exc
        return (response.text or "").strip()

    def available(self) -> tuple[bool, str]:
        try:
            self._client()
        except BackendUnavailable as exc:
            return False, str(exc)
        return True, f"SDK present, key set, default {self.model}"
