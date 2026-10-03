# Local & Hybrid Hosting Plan

This document is infrastructure strategy, not engine design — nothing here changes any role defined in `Director-Actor System Architecture.md`. It answers a different question: which backend (a local open-source model on your machine, or a cloud API) should serve each engine role, and why. Swapping a role's backend should always be a configuration change, the same way swapping World Packs is (see architecture doc §1) — never a redesign.

**Revised 2026-06-20: cloud tier is Gemini, not Claude.** No Claude API credits available, and Matt has Gemini API access, so every "Claude" reference below is now Gemini. The role-split *logic* (high-volume/lower-judgment → local, low-volume/high-judgment → cloud) is unchanged — only the cloud vendor changed. Because the router design (§4) treats the cloud tier as a config slot, this was a rename, not a redesign.

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


## 1. Hardware Ceiling — HISTORICAL, Dell 16 Plus (DB16250), Core Ultra 9 288V / 32GB *(NOT the target machine; see MACHINE IDENTITY above)*

**The relevant numbers.** Intel Core Ultra 9 288V: 8 cores / 8 threads, 3.3 GHz base / 5.1 GHz boost, 12MB L3, 30W TDP. Arc 140V integrated graphics (no discrete GPU on this machine). 32GB of LPDDR5X-8533 memory soldered on-package (not a separate VRAM pool — CPU, iGPU, and NPU all draw from the same 32GB), giving **136.5 GB/s of memory bandwidth**. NPU rated at 48 TOPS.

**The number that actually matters: bandwidth, not TOPS.** Autoregressive LLM generation (the token-by-token decoding Ollama/LM Studio do) is memory-bandwidth-bound — the bottleneck is how fast model weights stream from memory into the compute units, not how many TOPS a spec sheet claims. 136.5 GB/s sits well above plain dual-channel desktop DDR5 but far below a discrete GPU (a 4090 is roughly 1,000 GB/s). This is the figure that sets your tokens/second ceiling, and it doesn't change no matter which model you load.

**The NPU's 48 TOPS won't help here.** As of mid-2026, neither Ollama nor LM Studio nor llama.cpp routes chat-style LLM generation through the NPU — the NPU handles narrow fixed-function tasks (background blur, noise suppression, Windows Studio Effects), not token generation. Vendor TOPS numbers on "AI PC" spec sheets are real but mostly irrelevant to running a local LLM today. Don't factor the NPU into capacity planning.

**What 32GB shared memory actually allows**, leaving realistic headroom for Windows, a browser, and the orchestration code itself (figure 6–8GB of overhead before a model even loads):

| Model class | Q4_K_M size | Fits? | Expected feel |
|---|---|---|---|
| ~7–8B (e.g. Qwen3 8B) | ~5GB | Comfortable | Fast — benchmarked around 17–18 tok/s on this exact iGPU with GPU offload working, ~9 tok/s CPU-only |
| ~14B (e.g. Qwen3 14B) | ~9–10GB | Comfortable | Good balance — roughly 55–60% of the 8B's speed (speed scales inversely with parameter count under a fixed bandwidth ceiling), so figure ~10 tok/s |
| ~24–27B (e.g. Mistral Small 24B, Gemma 3 27B) | ~13–15GB | Tight but workable | Noticeably slower (rough estimate 5–8 tok/s); fine for an unattended draft, frustrating for rapid back-and-forth |
| ~30–32B+ | ~18–20GB+ | Marginal | Risk of swapping/instability with normal apps open; not recommended for interactive use |
| 70B-class | 35GB+ | Doesn't fit | Not realistic on 32GB shared memory regardless of quantization |

**GPU offload needs a specific setup, not the default install.** Stock Ollama on Windows doesn't reliably get full acceleration out of Intel's Arc 140V (Lunar Lake) iGPU yet — the documented working path is Intel's IPEX-LLM-enabled Ollama build. Install stock Ollama first and check actual tokens/sec; if it's running CPU-only (roughly half the GPU-offload speed), switch to the IPEX-LLM build. This is a one-time setup detail, not an ongoing tax.

## 2. Software: Ollama vs. LM Studio

Both run GGUF-quantized open models on this hardware; the difference is interface, not capability. **Recommend Ollama as the backend the Director/orchestration code talks to** — it's headless-first, exposes a local REST API (`localhost:11434`, with an OpenAI-compatible `/v1` surface), and that's exactly the shape a multi-agent orchestrator needs to call into programmatically. **LM Studio is useful as a side tool** for interactively trying and comparing candidate models through its chat UI before committing one to the engine — better for human evaluation, less suited to being the thing your code calls in a loop.

## 2a. Platforms That Actually Use the NPU — and Why That's Not a Speed Win

Neither Ollama nor LM Studio touch the NPU. A few platforms do exist that target it specifically:

- **OpenVINO + OpenVINO GenAI** (Intel's own toolkit) — the most actively maintained NPU path. Models export through Optimum-Intel from Hugging Face, quantized to INT4 (the NPU requires this; the iGPU/CPU paths don't), then run through `openvino-genai`. It can also serve over HTTP via **OpenVINO Model Server (OVMS)**, which means it could plug into the same Director-calls-a-local-endpoint pattern Ollama does — it's a real alternative backend, not just a demo tool. As of recent OpenVINO releases, NPU inference is capped at an 8K context window, smaller than what the iGPU path supports.
- **IPEX-LLM** (already named above for iGPU offload) **also has an NPU backend** — same Intel library, a different acceleration target, exposed via Python/C++ or a llama.cpp-compatible API.
- **Intel AI Playground** — Intel's own consumer app, explicitly tuned for Lunar Lake, ships with Phi-3/Qwen2/Mistral presets and can load custom models. Polished, but built as a standalone chat app rather than something with a robust API server — not well-suited to being called in a loop by an orchestrator.
- (AMD's "Lemonade" is the equivalent idea for Ryzen AI NPUs — not applicable here since this machine is Intel.)

**The catch: on this exact chip family, the NPU is slower than the iGPU, not faster.** Benchmarks on Lunar Lake show the NPU running at roughly 60–70% of the iGPU's tokens/second at the same INT4 quantization (one measured pair: ~6 tok/s on NPU vs. ~20 tok/s on iGPU), with slower time-to-first-token too (1.5–2.4s vs. under 1s). Counterintuitively, the iGPU also wins on energy-per-token despite drawing more instantaneous power, because its throughput is high enough to offset that. The NPU's appeal is lower absolute power draw and a separate execution unit, not raw speed — switching the Actor-drafting role to NPU would make turns slower, not faster.

**Where the NPU could still earn its keep here:** since the NPU and iGPU are separate execution units drawing from the same 32GB pool, running them *concurrently on two different jobs* could partially restore some of the parallelism §4 notes is lost when going local (one Actor's draft on the iGPU while a second, lower-priority job — a table read, or a second Actor's draft — runs on the NPU at the same time). This is a genuine DIY path, not a turnkey one: it means standing up OpenVINO GenAI or IPEX-LLM's NPU mode alongside Ollama and routing specific roles to each, plus living with INT4-only quantization and the 8K context cap on the NPU side. Worth treating as a later optimization to experiment with, not a starting setup — Ollama-on-iGPU alone is simpler and faster for any single role.

## 3. Model Recommendation

**Primary driver: one ~14B instruct model, Q4_K_M, loaded once.** This is the practical sweet spot for this machine — comfortable memory headroom, usable speed, and good instruction-following. Crucially, **one model instance can serve every Actor and the Director** — a Persona (architecture doc §2) is a system prompt, not a separate set of model weights, so there's no need to load multiple models for multiple characters. Loading more than one model concurrently on 32GB shared memory burns headroom fast for no real benefit here.

**Actual model in use: `deepseek-r1:14b`.** Originally recommended Qwen3 14B class, and Matt had `qwen3:14b` already pulled — but it turned out not to be GPU-offload-compatible with the IPEX-LLM Ollama portable build on this Arc 140V setup. `deepseek-r1:14b` is, and is now the model actually loaded for local roles. Worth tracking into the build roadmap: DeepSeek-R1 is a *reasoning* model — by default it emits a `<think>...</think>` block before its actual answer, a different output shape than a plain instruct model like Qwen3. Actor alt-drafting (§4 below) will need to strip the think-block before treating the remainder as in-character dialogue, or decide the reasoning trace is itself worth logging. Flag for Phase 1/2 output parsing, not a blocker now.

**Optional higher tier for unattended, quality-over-speed drafting:** a ~24–27B model when you're willing to wait longer for a noticeably stronger draft — e.g. drafting Actor alts for one pivotal scene rather than iterating turn-by-turn live.

**A caution on roleplay-finetuned "uncensored" community models** (MythoMax, Rocinante, Snowpiercer, and similar): forum consensus rates these well for raw creative range, but they're generally tuned to relax content restrictions, not to follow a system-prompt persona *more reliably*. Havenpass's tone has an explicit guardrail (cozy, not gory — see the World Pack style sheet, architecture doc §8); a mainstream instruct model that reliably respects a system prompt is the safer default. Worth experimenting with the RP-tuned models later if mainstream output feels flat, but not the starting choice.

## 4. Role Mapping: What Runs Local, What Calls Gemini

This is the actual hybrid design, and it follows from how often each role is called, not just how "smart" it needs to be — those two things turn out to point the same direction.

**Local (the high-volume, lower-judgment roles):**
- **Actor alt-drafting** (architecture doc §4, step 4) — by far the highest call volume in the whole turn loop: 2–3 alts, per Actor, every single turn. This is exactly the workload worth taking off the API meter, and a 14B local model drafting in-character dialogue from a well-specified persona and filtered brief is a reasonable fit.
- **Table read** (§4, step 3) — a cheap, low-stakes setup check by design; doesn't need frontier-model judgment to catch an obviously broken setup.

**Gemini API (the low-volume, high-judgment roles):**
- **Director arbitration** (§4, step 6) — checking a selected Actor output against established facts and producing a plausible/implausible verdict is exactly the kind of nuanced judgment call worth paying for, and it's called once per take, not once per alt.
- **Continuity Engine classification and patch drafting** (§7, §8) — runs only after the deterministic graph traversal narrows the candidate set, so it's already a small, infrequent workload (once per reshoot or World Pack edit) being asked to do real reasoning about whether a dependency is minor or major.
- **Manuscript Compiler** (§10) — style-sheet consistency checking, POV filtering, render-target content filtering, and the final polish pass all benefit from stronger prose-level judgment, and compilation happens in chapter-sized chunks, not per-turn.

**Which Gemini model.** Default to **Gemini 2.5 Flash** for this whole tier — strong enough for these structured judgment calls, and critically, its free-tier rate limit is roughly double Gemini 2.5 Pro's (low tens of requests/minute vs. closer to 5/minute for Pro, per Google's published limits, though these change — worth re-checking at ai.google.dev before relying on a specific number). Reserve **Gemini 2.5 Pro** as a per-call override for the rare unusually tricky judgment call (e.g., a genuinely ambiguous continuity conflict), the same override mechanism described below. A turn loop calling the cloud tier every scene-close, reshoot, and compile chunk will bump into free-tier RPM limits faster on Pro than on Flash — Flash-first keeps the engine usable without needing to enable billing right away.

**Why this split is also the economical one.** The part of the turn loop that happens *most often* — every Actor, every alt, every turn — is the part this plan moves off the API. The part that happens *least often* — once per scene close for arbitration, once per reshoot/edit for continuity, once per chunk for compilation — is the part that stays on Gemini. Paying frontier-model rates for the infrequent, judgment-heavy calls costs far less in absolute terms than paying them for the high-volume drafting calls would, and Gemini's free tier may cover this usage pattern entirely depending on session volume.

**One accepted tradeoff: "parallel Actor calls" (§11) doesn't parallelize locally.** That efficiency principle assumes elastic API compute, where N simultaneous Actor calls really do run at once. On a single iGPU with one loaded model, concurrent requests queue and serialize through the same memory bandwidth — there's only one execution path. This doesn't break anything; it just means a 3-Actor scene's local alt-drafting takes roughly 3× as long, wall-clock, as it would calling Gemini for all three in parallel. Worth knowing going in, not a flaw to fix — it's the explicit cost of moving that role off the API. (A partial, DIY mitigation using the NPU alongside the iGPU is noted in §2a, but it's an optimization to revisit later, not part of the starting setup.)

**Implementation shape:** a thin router in the Director config — one entry per logical role, each pointing at a backend (local Ollama endpoint or Gemini API, with a model-tier field for Flash vs. Pro), defaulting to the split above. Should be overridable per-scene (e.g., "run this Actor's alts through Gemini instead" or "use Pro instead of Flash for this one arbitration call" for an unusually important scene) without touching engine code, the same way a World Pack swap doesn't touch engine code. Swapping back to Claude later — or adding it as a second cloud option — is the same kind of config change, not a redesign, if credits become available again.

## 5. Looking Ahead: the tiiny.ai Pocket Lab (arriving ~August 2026)

**What it claims.** 80GB LPDDR5X memory, 1TB NVMe, built on the open-source PowerInfer/TurboSparse stack (sparse-activation inference with heterogeneous CPU/GPU/NPU scheduling), ~190 combined TOPS (30 CPU + 160 NPU), advertised support for models up to ~120B parameters locally, an OpenAI-API-compatible serving interface, no subscription or per-token fees.

**Why it matters for this plan.** 80GB removes the 32GB ceiling that currently rules out 70B-class models. If that holds up in practice, a much stronger local model becomes plausible — which would let some of the Gemini-reserved roles above (Continuity Engine classification, Director arbitration, possibly Manuscript Compiler polish) move local too, since a 70B-class model closes more of the quality gap on structured judgment tasks than a 14B model can.

**A real caveat: treat the specs as unverified until benchmarked.** Coverage of the Kickstarter campaign itself flagged that the device's marketed numbers outpace its independent benchmarks so far — it's a crowdfunded pre-order product, not a shipped, reviewed one, as of this writing. Worth re-running the role-mapping exercise in §4 once you actually have it and can measure real tokens/sec on a real workload, rather than planning against vendor claims now.

**No redesign needed to take advantage of it.** Because §4's role mapping is just config — a logical role pointed at a backend — moving a role from the laptop's Ollama endpoint to the tiiny.ai device's OpenAI-compatible endpoint is the same kind of change as moving it from local to Gemini. The engine itself doesn't need to know or care which physical machine is answering.

## 6. Summary

Run the Actor alt-drafting and table-read roles locally on a ~14B Q4 model via Ollama on this laptop — that's where the call volume lives, and it's a fully adequate fit for that workload. Keep Director arbitration, Continuity Engine classification/patching, and Manuscript Compiler work on Gemini (Flash by default, Pro as a per-call override) — that's where judgment quality matters most and call volume is naturally low, which also keeps usage within or close to Gemini's free tier. Revisit the split once the tiiny.ai device is in hand and benchmarked, since more local headroom may let more of the Gemini-reserved roles move over without giving up quality.
