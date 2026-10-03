# Havenpass

A director/actor multi-agent fiction engine, with **Havenpass** (a cozy fantasy
mystery) as its first story world.

One **Director** agent frames scenes and arbitrates what happens; several **Actor**
agents each draft in-character options from a brief filtered to what that character
could plausibly know; **you** pick (or write) each line. Every committed scene goes
through a film-set take discipline: draft, arbitrate, **dailies**, then you call
`print` or `ng`. Nothing reaches the shared state without that call.

The engine is world-agnostic: a story world is a *World Pack* (world bible, persona
set, initial social-state seed). This repository ships the engine and a minimal
Havenpass World Pack. The Havenpass world bible itself is not included.

## Status

Build phases are tracked in `Engine/Build Roadmap & Phasing.md`.

- **Phases 1 and 2 have run**: one Actor, then three Actors with per-Actor brief
  filtering.
- **Phase 3 is built on its deterministic side** (2026-09-04): the Take Ledger,
  marks/replay, dailies to print/NG, and the Continuity Engine's dependency walk,
  each with a self-test that needs no model. Its live half (one real reshoot with a
  dependent later scene, and the `continuity_classify` role) has not been run yet.
- Later phases (World Pack versioning, locations and story-time, the Manuscript
  Compiler, the dashboard) are designed in the architecture document but **not
  implemented**.

## Architecture in brief

- **Blackboard** (`Engine/blackboard.py`): an append-only, event-sourced JSONL log.
  Content events fold into state only when their {Scene ID, take} is that scene's
  active take. `print_take()` writes the ledger event last, so a crash leaves an
  inert take rather than a half-committed one.
- **Director** (`Engine/director.py`): frames scenes, builds each Actor's filtered
  brief (`known_by` facts), and arbitrates the picked lines into a changeset.
- **Actor** (`Engine/actor.py`): drafts 2-3 alternative lines per turn from a stable
  persona prefix plus the per-scene brief.
- **Continuity Engine, deterministic half** (`Engine/continuity.py`): on a reshoot,
  diffs the old active take against the new changeset and walks later scenes'
  `read_facts` forward to find what depends on a changed fact. Severity
  classification is a model role, not this module.
- **Backend router** (`Engine/backends/`): the engine names *roles*, never models.
  `backends/routing.json` maps each role to a backend:

  | Role | Backend (current routing) |
  | :-- | :-- |
  | `actor_draft`, `table_read` | Ollama, `deepseek-r1:14b` (local, high volume) |
  | `director_arbitration`, `continuity_classify` | Claude Code CLI, `sonnet` |
  | `manuscript_compile` | Claude Code CLI, `opus` |

  The cloud tier is reached through the `claude` CLI driven headless, one subprocess
  per call; there is no API key in this project. A Gemini adapter exists but is
  dormant; nothing routes to it. Overrides, in precedence order:
  `complete(..., backend=, model=)`, then `HAVENPASS_ROUTE_<ROLE>="backend:model"`,
  then `HAVENPASS_ROUTING=<path>`, then `routing.json`.

The full design is in `Engine/Director-Actor System Architecture.md`; hosting and
role-split reasoning is in `Engine/Local & Hybrid Hosting Plan.md`.

## Requirements

- **Python 3.11** (the docs use the Windows `py` launcher: `py -3.11`).
- **Python packages:** `ollama` and `python-dotenv`. Nothing else is needed for the
  current routing. `google-genai` is only needed if you route a role to Gemini.
- **Ollama**, running locally, with the actor model pulled:
  `ollama pull deepseek-r1:14b`.
- **The `claude` CLI (Claude Code)** on `PATH` and logged in, for the Director,
  continuity and compile roles. Set `CLAUDE_CLI` to its full path if it is not on
  `PATH`.

The self-tests below need none of the model backends.

## Setup

The engine's own notes keep the virtual environment outside the repository folder:

```pwsh
py -3.11 -m venv $HOME\.venvs\havenpass-engine
& $HOME\.venvs\havenpass-engine\Scripts\python.exe -m pip install ollama python-dotenv
```

No `.env` is required for the current routing. `load_dotenv()` reads `Engine/.env`
if it exists; that is where a backend credential would go if you repoint a role at a
backend that needs one. `.env` is gitignored.

`Engine/README.md` has more detail, including a workaround for pip certificate
errors behind TLS-intercepting antivirus.

## Running the self-tests (no model, no key, no network)

Run these from `Engine/` with the venv's interpreter:

```pwsh
cd Engine
python blackboard.py    # Take Ledger, marks/replay; also replays the recorded logs in Worlds/Havenpass/blackboard/
python continuity.py    # dependency walk over synthetic scene histories
python director.py      # brief filtering: known_by-restricted facts reach only the right Actors
```

Each prints `PASS` on success.

`python test_backends.py` checks each role's backend *preconditions* (SDK importable,
service answering, binary on PATH) and spends no model call. `python test_backends.py
--live` spends one real call per distinct backend.

## Running a scene

Run from `Engine/`. These call the real backends.

- **Interactive:** `python run_scene.py` runs a backend pre-flight first and refuses
  to start if a routed backend is unusable, then plays the Phase 2 three-Actor scene
  in the terminal, ending at the print/NG call.
- **Split, for picking lines outside a terminal prompt:**

  ```pwsh
  python run_scene_draft.py              # Actors draft alts -> Engine/LOGS_scratch_draft.json
  python run_scene_commit.py picks.json  # Director arbitrates your picks -> dailies (writes nothing to the blackboard)
  python run_scene_take.py print         # commit; this take becomes active   (or: ng to discard)
  ```

  `picks.json` maps each Actor to a 1-indexed choice from the drafted alts or to a
  literal line of your own, e.g. `{"Wen": 1, "Ruck": 2, "Klisp": "custom line"}`.

Note that the scene scripts append to the event logs under
`Worlds/Havenpass/blackboard/`, which are tracked in this repository as the recorded
output of the test phases.

## Repository layout

```
Engine/                                    the engine (world-agnostic)
  actor.py  director.py  blackboard.py  continuity.py
  run_scene.py  run_scene_draft.py  run_scene_commit.py  run_scene_take.py
  test_backends.py                         per-role backend precondition check
  backends/                                role router + Ollama / Claude Code / Gemini adapters, routing.json
  README.md                                engine notes: phase status, routing, setup, troubleshooting
  Director-Actor System Architecture.md    the full design
  Build Roadmap & Phasing.md               phases and their test gates
  Local & Hybrid Hosting Plan.md           which backend serves which role, and why
  Local Environment Setup.md               machine setup checklist (partly historical; see its header)
  Research Digest - Agent Architecture Sources.md   the research the design draws on
Worlds/
  Havenpass/
    world_pack.py                          minimal World Pack: personas + initial social state
    blackboard/*.jsonl                     recorded event logs from Phases 1-3
```

`run_scene*.py` and `blackboard.py` locate the world at
`Engine/../Worlds/Havenpass`, so keep `Engine/` and `Worlds/` side by side.

## Licence

MIT. See `LICENSE`.
