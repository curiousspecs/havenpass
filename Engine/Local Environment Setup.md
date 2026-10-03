# Local Environment Setup

> **MACHINE IDENTITY — READ BEFORE ANY HARDWARE CLAIM IN THIS FILE.**
> **TARGET MACHINE: the ACEMAGIC G3A — Intel Core i9-13900F (24C/32T, NO integrated GPU),
> NVIDIA RTX 2000 Ada with 16,380 MiB DEDICATED VRAM, ~31.8 GB system RAM, no NPU.**
> Decided 2026-09-12: the engine runs wherever Claude Code runs, and that is this box.
> Check the machine itself; do not trust this line alone.
> **Check in one command: `nvidia-smi` and `ollama ps`.**
>
> **EVERYTHING BELOW THAT DESCRIBES A Dell 16 Plus / Core Ultra 9 288V / Arc 140V / shared-32GB
> pool / NPU / IPEX-LLM is a 2026-06-19 scan of a DIFFERENT MACHINE and is RETAINED AS HISTORY,
> NOT AS A PRESENT-TENSE FACT.** A hardware check on the host measured the divergence on
> 2026-09-08; the reasoning behind the model
> choice and the IPEX-LLM prescription rested on an Arc-offload criterion **that does not exist on
> a CUDA card.** Stock Ollama on this box already reports `PROCESSOR = 100% GPU` at 44.9–56.1
> tok/s with nothing installed and nothing configured.
>
> **Revisit if** the engine moves to another machine — then re-state this header, do not edit
> the history below.


**⚠ HISTORICAL AS WRITTEN:** tailored to the 2026-06-19 system scan on the Dell 16 Plus (Core Ultra 9 288V / 32GB / Arc 140V) — **not the target machine.** On the ACEMAGIC G3A the acceleration check is `nvidia-smi` / `ollama ps`, not Task Manager → GPU (Arc 140V), and the Vulkan question in this file is moot (the card is NVIDIA). Picks up from `Local & Hybrid Hosting Plan.md` — this doc is the literal "do it" checklist, not new strategy.

## Already in place — no action needed

- Hardware matches the hosting plan's assumptions exactly: Ultra 9 288V, 32GB RAM, Arc 140V iGPU.
- **Ollama 0.30.9** installed and running, with three models already pulled: `qwen3:14b` (9.3GB), `llama3.2:3b-instruct-q8_0`, `mistral:7b`. (2026-06-20: `qwen3:14b` turned out not to be GPU-offload-compatible with the IPEX-LLM Ollama portable build — switched to `deepseek-r1:14b`, which is. See `Local & Hybrid Hosting Plan.md` §3.)
- **Docker 28.3.2** + **WSL2** (Ubuntu and docker-desktop distros) installed, currently stopped. Not needed yet — see "Defer" below.
- **Python**: 3.13.14 (default) and 3.11 both installed via the `py` launcher. No AI/ML pip packages installed yet on either — clean slate.

## Step 1 — Confirm whether GPU offload is already working

Ollama added experimental Vulkan GPU support for non-NVIDIA cards starting around v0.12.6, and version 0.30.9 is well past that, so there's a real chance Arc 140V acceleration is already active with zero extra install. Check before installing anything else:

1. In one terminal: `ollama run qwen3:14b "Say hello in one sentence."`
2. While that's running, in a second terminal: `ollama ps` — look at the `PROCESSOR` column. `100% GPU` (or a GPU/CPU split) means Vulkan offload is working. `100% CPU` means it isn't.
3. Cross-check with Task Manager → Performance → GPU (Arc 140V) — usage should spike during generation if it's offloading.

If GPU usage shows up, skip Step 2 entirely.

## Step 2 — Only if Step 1 shows CPU-only: IPEX-LLM Ollama portable zip

Intel's IPEX-LLM ships a **self-contained portable build** — no separate driver/toolkit install, no rebuild of Ollama.

1. Download the Windows "Ollama Portable Zip" from the [intel/ipex-llm releases page](https://github.com/intel/ipex-llm/releases) (look for the latest `ollama-ipex-llm-*-win.zip`).
2. Extract it to a folder, e.g. `C:\ipex-llm-ollama`.
3. Point it at the models you already pulled instead of re-downloading: set the environment variable `OLLAMA_MODELS` to `C:\Users\<you>\.ollama\models` before starting it (`set OLLAMA_MODELS=C:\Users\<you>\.ollama\models` in the same Command Prompt session, or set it permanently via System Properties → Environment Variables).
4. **Quit stock Ollama first** (system tray icon → Quit, or it'll fight over port 11434) — IPEX-LLM's build serves the same Ollama API on the same port.
5. Run `start-ollama.bat` from the extracted folder.
6. Repeat the Step 1 check (`ollama ps`) to confirm GPU usage now appears.

This is the documented fallback if upstream Vulkan support isn't yet stable on this build — full instructions and troubleshooting at the [IPEX-LLM Ollama Quickstart](https://github.com/intel/ipex-llm/blob/main/docs/mddocs/Quickstart/ollama_quickstart.md).

## Step 3 — Python environment for the engine code (Phase 0 of the build roadmap)

**Use Python 3.11, not 3.13**, for this project specifically. OpenVINO's runtime has only just added 3.13 support and its companion tools (NNCF, etc.) haven't fully caught up yet, and IPEX-LLM's 3.13 compatibility isn't clearly documented. 3.11 is the safer choice across the whole local-AI tooling stack this project may touch (Ollama's Python client, eventually OpenVINO GenAI if the NPU-concurrency idea in the hosting plan's §2a gets explored).

**⛔ STALE AS WRITTEN — CORRECTED 2026-08-22. Do NOT create the venv in `Engine\`.** It goes OUTSIDE
the cloud-synced working tree, e.g. at `$HOME\.venvs\havenpass-engine`; a venv inside `Engine\` meant
**6,174 files** syncing to the cloud for something one command rebuilds. That was decided 2026-08-17
and recorded in `README.md`, and this block was never updated to match — a session following this file
literally will build the wrong thing, which is exactly what happened on 2026-08-22 before the README
caught it. `README.md` governs; this is the pointer.

```pwsh
py -3.11 -m venv $HOME\.venvs\havenpass-engine
& $HOME\.venvs\havenpass-engine\Scripts\python.exe -m pip install ollama python-dotenv
```

**`google-genai` is deliberately NOT installed** — the key was deleted 2026-08-17 and no role routes to
Gemini. The Claude tier needs no SDK; it shells out to the `claude` CLI. Install a backend when
`backends/routing.json` actually points a role at it, and not before.

Create a `.env` file in `Engine\` (and add `.env` to `.gitignore` once git is initialized) holding:

```
GEMINI_API_KEY=...
```

That's the complete Phase 0 dependency list per the build roadmap — just enough to call both backends. (Switched from Claude to Gemini on 2026-06-20 — no Claude API credits available; see `Local & Hybrid Hosting Plan.md` §4 for the updated role mapping. The `google-genai` SDK auto-detects `GEMINI_API_KEY` from the environment, so no key needs to be passed in code by hand.)

## Step 4 — git

Confirmed: git 2.50.1 is installed. Nothing to do here — Phase 0's git requirement (engine code only, kept separate from the in-fiction event log's own history) is already satisfied.

## Defer — Docker / OpenVINO Model Server

Leave Docker stopped for now. It isn't needed for Phases 0–6 of the build roadmap (everything routes through Gemini or plain Ollama). It becomes relevant only if you later want to experiment with the hosting plan's §2a idea — running OpenVINO Model Server (commonly distributed as a Docker image) alongside Ollama to use the NPU and iGPU concurrently on two different jobs. That's an optimization to revisit in or after Phase 7, not a Phase 0 task.
