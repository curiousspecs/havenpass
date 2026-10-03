"""
Claude Code adapter -- the build-time model, per Matt's ruling of 2026-08-17:

    "I would like the final project to be model-agnostic, but as we build it,
     Claude through Claude Code needs to be the model."

That sentence is why this whole package exists. The hosting plan's cloud tier
was Gemini; the key is gone; and the engine had no seam at which to swap a
tier, so a model change was an engine change. Now it is a config edit.

## ⛔ HOW THIS REACHES THE MODEL, AND WHAT IT COSTS

There is no Anthropic API key in this project -- the bring-your-own-key
budget was exhausted, and the Gemini key was deleted rather than replaced.
The only route to Claude that exists on this machine is the **Claude Code CLI**,
driven headless: `claude -p <prompt> --system-prompt <s> --output-format text`.

**The costs, stated up front rather than discovered in a turn loop:**

1. **It is a subprocess per call, not a connection.** Process startup dominates
   short completions. This is acceptable for the roles routed here -- arbitration
   runs once per take, not once per alt -- and it is NOT acceptable for Actor
   alt-drafting, which is why the routing table leaves that on Ollama.
2. **It depends on a CLI being installed and logged in.** That is a real,
   external precondition; `available()` checks for the binary, and nothing here
   can check the auth state without spending a call.
3. **It is agentic by default.** Tools are disabled explicitly below
   (`--max-turns 1`, no allowed tools, permission-mode deny-ish) because this is
   a completion call, not an agent run: the engine wants text back, not a
   session that decides to read files.
4. **Determinism is not offered.** No temperature/seed control through this
   surface. The engine's take-gating design already assumes regeneration varies.

**If an API key ever arrives, the right change is a NEW adapter beside this one
and one line in `routing.json` -- not an edit to this file.** That is the whole
claim the seam is making.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .base import BackendCallFailed, BackendUnavailable

DEFAULT_MODEL = "sonnet"  # role tier, not a pinned id: the CLI resolves aliases,
                          # so the engine does not carry a model id that expires.
                          # Override per role in routing.json ("opus" for judgment).

DEFAULT_TIMEOUT = 180  # seconds. A subprocess that hangs must fail the take, not
                       # the session -- an unbounded wait here would stall a scene
                       # with a half-written changeset, which is the exact failure
                       # take-gating exists to prevent.


class ClaudeCodeBackend:
    name = "claude_code"

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT, **_ignored):
        self.model = model
        self.timeout = timeout

    def _binary(self) -> str:
        exe = os.environ.get("CLAUDE_CLI") or shutil.which("claude")
        if not exe:
            raise BackendUnavailable(
                "the `claude` CLI is not on PATH. This backend drives Claude Code "
                "headless; install it, or set CLAUDE_CLI to its full path."
            )
        return exe

    def complete(self, prompt: str, *, system: str | None = None, model: str | None = None) -> str:
        exe = self._binary()
        cmd = [
            exe,
            "-p", prompt,
            "--output-format", "text",
            "--model", model or self.model,
            "--max-turns", "1",          # a completion, not an agent run
            "--allowed-tools", "",       # no tool use: text in, text out
        ]
        if system:
            cmd += ["--system-prompt", system]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                # cwd is deliberately NOT the Engine folder: a headless completion
                # has no business inheriting a project context it might read.
                cwd=os.path.expanduser("~"),
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendCallFailed(
                f"`claude -p` exceeded {self.timeout}s and was killed. Subprocess "
                "startup plus generation is the cost of this backend; raise the "
                "timeout in routing.json or route this role elsewhere."
            ) from exc
        except OSError as exc:
            raise BackendCallFailed(f"could not launch {exe!r}: {exc}") from exc

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()[:800]
            raise BackendCallFailed(
                f"`claude -p` exited {proc.returncode}. stderr: {stderr or '(empty)'}"
            )
        text = (proc.stdout or "").strip()
        if not text:
            raise BackendCallFailed(
                "`claude -p` exited 0 with empty stdout. A clean exit code is not "
                "evidence of a response."
            )
        return text

    def available(self) -> tuple[bool, str]:
        exe = os.environ.get("CLAUDE_CLI") or shutil.which("claude")
        if not exe:
            return False, "`claude` CLI not on PATH (set CLAUDE_CLI to override)"
        try:
            proc = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=30
            )
        except Exception as exc:
            return False, f"`claude --version` failed: {exc}"
        if proc.returncode != 0:
            return False, f"`claude --version` exited {proc.returncode}"
        # ⛔ Deliberately NOT a login check. Nothing here can verify auth without
        # spending a call, and reporting "available" on a version string is a
        # hint, not a guarantee -- said plainly so the pre-flight is not misread.
        return True, f"{(proc.stdout or '').strip()} (binary present; auth NOT verified)"
