# Havenpass Engine

Phases 1 and 2 have run. **Phase 3 is BUILT on its deterministic side (2026-09-04)** --
Take Ledger, marks/replay, dailies -> print/NG, and the Continuity Engine's dependency
walk, each with a no-model self-test -- and its live gate (one real reshoot, conflict
report reviewed) is the next thing to run. See `Build Roadmap & Phasing.md`.

## Phase 3 in one paragraph

`blackboard.py` now carries the **Take Ledger** (§7): content events fold into state
only when their {Scene ID, take} is the scene's ACTIVE take; `print_take()` writes the
content then a `take_printed` ledger event LAST (crash-safe); `ng_take()` retains the
discarded changeset and never folds it; `marks(log, scene_id)` is the state a scene
starts from (earlier scenes' active takes, exclusive); logs written before the ledger
replay unchanged (regression-tested against the real files). The turn loop is now
draft -> arbitrate -> **dailies** -> the user calls `print` or `ng`:
`run_scene_draft.py` -> `run_scene_commit.py picks.json` (stages, writes NOTHING) ->
`run_scene_take.py print|ng`. `continuity.py` is the deterministic half of the
Continuity Engine: `reshoot_report()` diffs the old active take against a new changeset
and walks later scenes' `read_facts` (recorded on every plot entry from Phase 3 on)
transitively; entries without `read_facts` are reported `unknown-reads`, never scored
unaffected. Severity and patches are the `continuity_classify` role's, not this module's.
Run `python blackboard.py`, `python continuity.py`, `python director.py` for the gates.

## ⛔ The engine names ROLES, not models

Every model call goes through **one seam**: `backends/`, the router
`Local & Hybrid Hosting Plan.md` §4 specified at Phase 0 and which was not built
until **2026-08-22**. Until then `actor.py` called `ollama.chat` directly and
`director.py` built a Gemini client directly — which is why the 2026-08-17 model
change had to edit engine files. It should have been a config edit.

```python
from backends import complete, preflight
text = complete("director_arbitration", prompt)   # a ROLE. Not a vendor.
```

**Which backend serves which role lives in `backends/routing.json`. Edit that file,
not the engine.** Current split, following call volume per §4:

| Role | Backend | Why |
| :-- | :-- | :-- |
| `actor_draft` | Ollama `deepseek-r1:14b` | highest-volume call in the turn loop — 2-3 alts, per Actor, per turn |
| `table_read` | Ollama `deepseek-r1:14b` | cheap, low-stakes setup check |
| `director_arbitration` | Claude Code `sonnet` | nuanced judgment, once per take |
| `continuity_classify` | Claude Code `sonnet` | runs after the deterministic graph walk narrows candidates |
| `manuscript_compile` | Claude Code `opus` | prose-level judgment, chapter-sized chunks |

**The cloud tier is Claude Code**, per Matt 2026-08-17: *"I would like the final
project to be model-agnostic, but as we build it, Claude through Claude Code needs
to be the model."* It is driven headless as a **subprocess per call** (`claude -p`)
because there is no API key in this project. That cost is why `actor_draft` stays
local and must not be routed here — see `backends/claude_code_backend.py`, which
states the four costs plainly.

**Gemini is dormant, not deleted** (`backends/gemini_backend.py`). Model-agnostic
means a backend can be absent without breaking the engine.

**Per-scene / per-call overrides**, in precedence order: `complete(..., backend=, model=)`
→ env `HAVENPASS_ROUTE_<ROLE>="backend:model"` → env `HAVENPASS_ROUTING=<path>` →
`routing.json`.

### Pre-flight before every scene

`run_scene.py` calls `director.preflight()` first and refuses to start if a routed
backend is unusable. The failure it prevents: Actors draft, the user reads every alt
and picks their lines, and *then* the Director's backend turns out to be unreachable —
a scene half-played, nothing committed, the user's authorial choices thrown away.

**A passing pre-flight is not a passing call.** It checks preconditions (SDK
importable, service answering, binary on PATH, key present). `python test_backends.py
--live` spends a real call per backend when you need actual evidence.

For the full design and rationale, see the companion docs in this folder:
`Build Roadmap & Phasing.md`, `Director-Actor System Architecture.md`,
`Local & Hybrid Hosting Plan.md`, and `Local Environment Setup.md`.

## Prerequisites

- **Python 3.11** (use the `py` launcher: `py -3.11`). 3.11 is preferred over 3.13
  for compatibility across the local-AI tooling stack — see `Local Environment Setup.md`.
- **Ollama** running locally with the `deepseek-r1:14b` model pulled:
  ```pwsh
  ollama pull deepseek-r1:14b
  ollama list   # confirm it's present; the Ollama service must be running
  ```
- **The `claude` CLI on PATH**, logged in. This is how the cloud-tier roles reach
  Claude; there is no API key in this project. Override the location with `CLAUDE_CLI`.
- **No Gemini API key.** It was deleted 2026-08-17 on Matt's instruction and revoked at
  the provider. The Gemini backend is dormant and nothing routes to it.

## Environment setup

**⛔ THE VENV LIVES OUTSIDE THIS FOLDER, DELIBERATELY: e.g. `$HOME\.venvs\havenpass-engine`.**
The original working copy sat inside a cloud-synced folder, and a venv there meant **6,174 files** syncing to the
cloud for something one command rebuilds. Rebuilt outside the synced folder 2026-08-17.

```pwsh
py -3.11 -m venv $HOME\.venvs\havenpass-engine
& $HOME\.venvs\havenpass-engine\Scripts\python.exe -m pip install ollama python-dotenv
```

**`google-genai` and `anthropic` are intentionally NOT installed.** The Gemini path is dormant behind a
lazy import in `backends/gemini_backend.py` (it lived in `director._gemini_client()` until the router
landed 2026-08-22), and `anthropic` was residue from a plan reversed in June. The Claude tier needs no
SDK at all — it shells out to the `claude` CLI. **Install a backend only when a role actually routes to
it**, and `backends/routing.json` is the file that says which do.

**⚠ If `pip` fails with `CERTIFICATE_VERIFY_FAILED`, it is AVG, not the network.** AVG intercepts TLS on
this machine (`SSLKEYLOGFILE=\\.\avgMonFltProxy\...`). Modern pip uses the OS trust store and works;
the pip *bundled into a fresh venv* is older, uses vendored certs, and fails. Do not disable certificate
verification. Download with the system interpreter's pip, then install offline:

```pwsh
py -3.11 -m pip download --dest <dir> ollama python-dotenv
& $HOME\.venvs\havenpass-engine\Scripts\python.exe -m pip install --no-index --find-links <dir> ollama python-dotenv
```

**No `.env` is required for the current routing.** `load_dotenv()` still runs, so a
   `.env` in `Engine\` is read if present — that is where a backend credential would go if
   a role is ever repointed at one that needs a key. `.env` is gitignored and must never be
   committed. `GEMINI_API_KEY` is the only key any adapter looks for, and nothing routes to
   Gemini today.

## Verifying the setup

**Start with the gate that needs no model, no key and no network** — the Phase 2 brief-filtering test,
which is pure logic and should always pass:

```pwsh
& $HOME\.venvs\havenpass-engine\Scripts\python.exe director.py
```

Expected: `PASS: brief filtering correctly isolates known_by-restricted facts per actor...`

`test_backends.py` then confirms the *model* backends answer:

```pwsh
& $HOME\.venvs\havenpass-engine\Scripts\python.exe test_backends.py
```

**It reads `backends/routing.json` and reports per ROLE** — add a role or repoint one and this test
follows automatically; there is nothing in it to keep in sync. It checks preconditions only and spends
no call. Add `--live` to spend one real call per distinct backend when you need evidence rather than a
green precondition:

```pwsh
& $HOME\.venvs\havenpass-engine\Scripts\python.exe test_backends.py --live
```

**⚠ Gemini no longer appears at all** — as of 2026-08-22 no role routes to it, so nothing tests it. The
key was deleted 2026-08-17 on Matt's instruction. That is the intended state, not a regression.

### Troubleshooting

- **`ModuleNotFoundError: No module named 'dotenv'`** — you're using the global
  Python instead of the venv. Run the interpreter by its full path above.
- **Script hangs on the Ollama test** — the model is cold-loading on first call.
  Wait for it to finish, or pre-warm with
  `ollama run deepseek-r1:14b "hi"` before running the test.
- **A role reports `unknown role`** — the name is not in `backends/routing.json`. The router
  refuses rather than falling back to a default: a wrong model quietly answering is worse
  than a crash and much harder to find later.
- **`claude` CLI not on PATH** — install Claude Code, or set `CLAUDE_CLI` to its full path.
  Note the pre-flight can only see the *binary*; it cannot verify you are logged in without
  spending a call, and it says so in its own output rather than implying otherwise.
- **Gemini reports a missing/placeholder key** — expected. The key is gone by decision. Only
  relevant if you have deliberately repointed a role at `gemini` in `routing.json`.
