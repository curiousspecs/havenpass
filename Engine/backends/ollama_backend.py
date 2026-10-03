"""
Ollama adapter -- the local tier (`Local & Hybrid Hosting Plan.md` §3, §4).

Serves the high-volume, lower-judgment roles: Actor alt-drafting (every alt,
every Actor, every turn) and the table read. Default model `deepseek-r1:14b`,
chosen ORIGINALLY because it was GPU-offload-compatible with the IPEX-LLM Ollama
build on a Dell 16 Plus / Arc 140V machine where `qwen3:14b` was not.
⛔ THAT CRITERION DOES NOT APPLY TO THE TARGET MACHINE (2026-09-12 ruling): the
ACEMAGIC G3A has no Intel GPU and a CUDA RTX 2000 Ada, and stock Ollama reports
100% GPU with nothing installed. The model choice may still be fine; the REASON
recorded for it is void here. The <think>-block note below is unaffected.

⛔ THINK-BLOCK STRIPPING LIVES HERE NOW, and that is the point of the seam.
deepseek-r1 is a *reasoning* model: it emits <think>...</think> before its real
answer. That is a property of the MODEL, so the engine should never have known
about it. actor.py's own _strip_think() is left in place and is now a harmless
second pass -- the operation is idempotent, and removing it in the same change
that moves it would have made a routing change and a behaviour change
indistinguishable in one diff.
"""

from __future__ import annotations

import re

from .base import BackendCallFailed, BackendUnavailable

DEFAULT_MODEL = "deepseek-r1:14b"

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str = DEFAULT_MODEL, **_ignored):
        self.model = model

    def _client(self):
        try:
            import ollama
        except ImportError as exc:
            raise BackendUnavailable(
                "the 'ollama' package is not installed in this environment "
                "(pip install ollama)"
            ) from exc
        return ollama

    def complete(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        ollama = self._client()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            response = ollama.chat(model=model or self.model, messages=messages)
        except Exception as exc:  # ollama raises its own ResponseError, plus httpx errors
            raise BackendCallFailed(
                f"ollama.chat failed for model {model or self.model!r}: {exc}. "
                "Check that the Ollama service is running and the model is pulled "
                "(`ollama list`)."
            ) from exc
        raw = response["message"]["content"]
        return _THINK_BLOCK.sub("", raw).strip()

    def available(self) -> tuple[bool, str]:
        try:
            ollama = self._client()
        except BackendUnavailable as exc:
            return False, str(exc)
        try:
            models = [m.get("model") or m.get("name") for m in ollama.list().get("models", [])]
        except Exception as exc:
            return False, f"Ollama service unreachable: {exc}"
        if self.model not in models:
            return False, f"model {self.model!r} not pulled (have: {', '.join(models) or 'none'})"
        return True, f"service up, {self.model} present"
