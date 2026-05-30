"""
pipeline_factory.py - build a Pipecat voice pipeline. OWNER: Rayan.
SCAFFOLD: the OUR-logic parts (per-turn guardrail reload + TurnEvent emission + brain interface)
are here; copy the exact STT/LLM/TTS service construction from bot-nemotron.py where marked TODO.
Heavy imports are inside build_pipeline() so `import pipeline_factory` never fails in text-only work.
"""
from contracts import append_event, TurnEvent, load_guardrails

def build_pipeline(system_prompt, tools=None, transport=None, on_event=None):
    # --- TODO (Rayan, Slice A.1): copy service setup from bot-nemotron.py ---
    # from pipecat.services...  STT = Nemotron Speech Streaming ; LLM = Nemotron via NEMOTRON_LLM_URL ;
    # TTS = Gradium ; assemble Pipeline([...]); use `transport` (SmallWebRTC now, Twilio later).
    #
    # OUR logic to wire into the LLM step:
    #   - each turn, reload guardrails: gr = load_guardrails()  and inject into the system prompt
    #     via brain.build_messages(...) so a patch mid-call takes effect immediately.
    #   - on each spoken turn, emit a TurnEvent:
    #       append_event(TurnEvent(speaker="envoy", text=..., latency_ms=...))
    #     so Rushil's dashboards render the live call.
    raise NotImplementedError("Slice A.1: copy bot-nemotron.py service setup, then wire the two hooks above.")
