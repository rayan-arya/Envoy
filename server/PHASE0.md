# Phase 0 - foundation (Rayan, ~1 hr, blocking)

Goal: everyone can import a shared foundation and Rushil can build the brain + self-heal in TEXT
while Rayan builds voice. Nobody forks into parallel work until this is pushed.

## Steps
1. Fork + clone the starter (git.new/ai -> pipecat-ai/yc-voice-agents-hackathon). Work in `server/`.
2. `cp .env.example .env` and paste the event endpoints:
       NVIDIA_ASR_URL=ws://44.241.251.184:8080
       NEMOTRON_LLM_URL=http://nemotron-fleet-1322439314.us-west-2.elb.amazonaws.com/v1
       NEMOTRON_LLM_MODEL=nvidia/nemotron-3-super
       GRADIUM_API_KEY=...          # provided at event
   (verify the exact URLs against the README at the event - they may rotate.)
3. `uv sync` then `uv run bot-nemotron.py` -> localhost:7860, confirm round-trip audio. PASS/FAIL.
4. Drop these files into `server/` (this scaffold). `uv add openai`.
5. Verify the foundation:
       uv run smoke_text.py        # proves the TEXT path (Envoy vs counterpart) - unblocks Rushil
       uv run python -c "import contracts, llm_client, brain, counterpart.persona, selfheal.monitor, pipeline_factory; print('imports OK')"
6. Commit "phase 0: foundation + contracts (locked)" and push. Ping the team to pull.

## What's locked
- `contracts.py` is the single source of truth. Only Rayan edits it; changes need a 5-min huddle.
- `llm_client.py` is the shared text LLM call (both import).
- `brain/` exports SYSTEM_PROMPT, TOOL_SCHEMAS, build_messages (Rushil owns the bodies; Rayan's pipeline imports them).

## Ownership (single-owner dirs - no merge conflicts)
- Rayan: contracts.py, llm_client.py, pipeline_factory.py, envoy/, telephony/, integrations/, infra/, config
- Rushil: brain/, counterpart/, selfheal/, dashboards/, evals/
- Shared state files: data/guardrails.json (Rushil writes / Rayan reads), data/events.jsonl (Rayan writes / Rushil reads)
- Rule: need something in the other's file or contracts.py? Post in chat - don't edit it.
