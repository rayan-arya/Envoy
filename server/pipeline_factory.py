"""
pipeline_factory.py - build a Pipecat voice pipeline. OWNER: Rayan.

Adapts the working STT/LLM/TTS construction from bot-nemotron.py (Nemotron STT, Nemotron LLM,
Gradium TTS) and wires in the two OUR-logic hooks:

  Hook A - live guardrail reload: a GuardrailInjector rebuilds the system prompt EVERY turn via
           brain.build_messages(transcript, guardrails, constraints), reading data/guardrails.json
           fresh each time. It runs even when there are zero guardrails, so the live-reload path is
           exercised from turn 1 - when Rushil's patcher writes a rule mid-call it just takes effect
           with no pipeline change.

  Hook B - real TurnEvents: a TurnEventObserver writes a TurnEvent (speaker, text, latency_ms) to
           data/events.jsonl each turn. latency_ms is the wall-clock turn gap (other party stops ->
           this party starts), measured off the pipeline clock.

Heavy imports live INSIDE build_pipeline() so `import pipeline_factory` stays light for text-only work.
"""
from contracts import append_event, TurnEvent, load_guardrails


def build_pipeline(system_prompt, tools=None, transport=None, on_event=None, constraints=None):
    """Assemble the real voice pipeline and return its PipelineWorker.

    Args:
        system_prompt: brain.SYSTEM_PROMPT (accepted for compatibility; the live system prompt is
            owned by the LLMContext and rebuilt each turn by brain.build_messages via the injector).
        tools: list of enabled tool names. "end_call" wires the real hang-up tool (EndTaskFrame).
        transport: the Pipecat transport (SmallWebRTC for A.1; Twilio in A.3).
        on_event: callback(TurnEvent) -> None for turn emission. Defaults to contracts.append_event.
        constraints: the booking constraints dict passed into brain.build_messages each turn.

    The transport's client-connected/disconnected handlers are registered here (Envoy speaks first).
    """
    import asyncio
    import os
    from collections import deque

    from loguru import logger
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        EndTaskFrame,
        FunctionCallResultProperties,
        LLMContextFrame,
        LLMRunFrame,
        TranscriptionFrame,
        TTSTextFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.observers.base_observer import BaseObserver, FramePushed
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.services.gradium.tts import GradiumTTSService
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.turns.user_turn_strategies import FilterIncompleteUserTurnStrategies

    import brain
    from contracts import BookingResult
    from integrations.calendar import create_event as cal_create_event
    from integrations.gmail import send_confirmation as gmail_send_confirmation
    from nemotron_llm import VLLMOpenAILLMService
    from nvidia_stt import NVidiaWebSocketSTTService

    on_event = on_event or append_event
    constraints = constraints or {}
    enabled_tools = ["end_call", "create_event", "send_confirmation"] if tools is None else list(tools)

    # --- Services (copied from bot-nemotron.py) -----------------------------------------------
    # Speech-to-Text: Nemotron streaming STT over WebSocket (16-bit PCM, 16 kHz, mono).
    stt = NVidiaWebSocketSTTService(
        url=os.getenv("NVIDIA_ASR_URL", ""),
        strip_interim_prefix=True,
    )

    # LLM: Nemotron-3-Super over vLLM (OpenAI-compatible /v1). NOTE the deliberate difference from
    # bot-nemotron.py: we do NOT set Settings.system_instruction. The system prompt is owned by the
    # LLMContext and rebuilt every turn by GuardrailInjector, so a mid-call guardrail patch is live.
    enable_thinking = os.getenv("NEMOTRON_ENABLE_THINKING", "false").lower() == "true"
    llm = VLLMOpenAILLMService(
        api_key=os.getenv("NEMOTRON_LLM_API_KEY") or os.getenv("NVIDIA_API_KEY", "EMPTY"),
        base_url=os.getenv("NEMOTRON_LLM_URL", ""),
        settings=VLLMOpenAILLMService.Settings(
            model=os.getenv("NEMOTRON_LLM_MODEL", "nvidia/nemotron-3-super"),
            extra={"extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}}},
        ),
    )

    # Text-to-Speech: Gradium.
    tts = GradiumTTSService(
        api_key=os.environ["GRADIUM_API_KEY"],
        settings=GradiumTTSService.Settings(
            voice=os.getenv("GRADIUM_VOICE_ID", "Eu9iL_CYe8N-Gkx_"),
        ),
    )

    # --- Tools: real side effects (agreed names live in brain.TOOL_SCHEMAS, implemented here) ----
    # Per-call state for idempotency + chaining (fresh per connection):
    #   events: confirmation_ref -> {event_id, html_link}   emails: set of confirmation_refs sent
    booking_state = {"events": {}, "emails": set()}

    def _booking_from_args(venue, time, confirmation_ref, party_size, price_estimate, notes):
        return BookingResult(
            success=True, venue=venue or "", time=time or "", party_size=int(party_size or 0),
            price_estimate=float(price_estimate or 0.0), confirmation_ref=confirmation_ref or "",
            notes=notes or "",
        )

    async def end_call(params: FunctionCallParams) -> None:
        """End the call. Only call this AFTER you have said goodbye in the same turn. The pipeline
        flushes any queued speech, then actually ends the session via EndTaskFrame."""
        logger.info("end_call invoked - pushing EndTaskFrame upstream (real session end)")
        await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        # run_llm=False: don't generate a follow-up; the goodbye is already in flight.
        await params.result_callback({"ok": True}, properties=FunctionCallResultProperties(run_llm=False))

    async def create_event(
        params: FunctionCallParams, venue: str, time: str, confirmation_ref: str,
        party_size: int = 0, price_estimate: float = 0.0, notes: str = "",
    ) -> None:
        """Add the CONFIRMED reservation to the user's Google Calendar. Call this ONLY after the
        counterpart has confirmed the booking AND given a confirmation reference - never speculatively.

        Args:
            venue: The restaurant / venue name.
            time: The reservation time as spoken, e.g. "7:00 PM".
            confirmation_ref: The booking's confirmation number/reference from the counterpart.
            party_size: Number of people in the party.
            price_estimate: Estimated total price, if known.
            notes: Any extra notes (seating, dietary, etc.).
        """
        if not (venue and time and confirmation_ref):
            await params.result_callback({"ok": False, "error": "booking not confirmed yet: need venue, time, and confirmation_ref before adding to the calendar"})
            return
        if confirmation_ref in booking_state["events"]:  # idempotent: don't double-create
            await params.result_callback({"ok": True, "idempotent": True, **booking_state["events"][confirmation_ref]})
            return
        booking = _booking_from_args(venue, time, confirmation_ref, party_size, price_estimate, notes)
        # google client is synchronous/blocking - run off the event loop so the pipeline isn't stalled.
        result = await asyncio.to_thread(cal_create_event, booking)
        if result.get("ok"):
            booking_state["events"][confirmation_ref] = {"event_id": result.get("event_id"), "html_link": result.get("html_link")}
        await params.result_callback(result)

    async def send_confirmation(
        params: FunctionCallParams, venue: str, time: str, confirmation_ref: str,
        party_size: int = 0, price_estimate: float = 0.0, notes: str = "",
    ) -> None:
        """Email the user a confirmation of the CONFIRMED reservation. Includes the calendar link if
        create_event already ran this call. Call this ONLY after the booking is confirmed.

        Args:
            venue: The restaurant / venue name.
            time: The reservation time as spoken, e.g. "7:00 PM".
            confirmation_ref: The booking's confirmation number/reference.
            party_size: Number of people in the party.
            price_estimate: Estimated total price, if known.
            notes: Any extra notes.
        """
        if not (venue and time and confirmation_ref):
            await params.result_callback({"ok": False, "error": "booking not confirmed yet: need venue, time, and confirmation_ref before emailing"})
            return
        if confirmation_ref in booking_state["emails"]:  # idempotent: don't double-send
            await params.result_callback({"ok": True, "idempotent": True, "note": "confirmation already emailed this call"})
            return
        booking = _booking_from_args(venue, time, confirmation_ref, party_size, price_estimate, notes)
        event_link = booking_state["events"].get(confirmation_ref, {}).get("html_link")  # chained
        result = await asyncio.to_thread(gmail_send_confirmation, booking, event_link)
        if result.get("ok"):
            booking_state["emails"].add(confirmation_ref)
        await params.result_callback(result)

    _tool_impls = {"end_call": end_call, "create_event": create_event, "send_confirmation": send_confirmation}
    tool_functions = [_tool_impls[name] for name in enabled_tools if name in _tool_impls]
    tools_schema = ToolsSchema(standard_tools=tool_functions)
    for fn in tool_functions:
        llm.register_direct_function(fn)

    # --- Context + aggregators (copied from bot-nemotron.py) -----------------------------------
    context = LLMContext(tools=tools_schema)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=FilterIncompleteUserTurnStrategies(),
        ),
    )

    # --- Hook A: GuardrailInjector (live guardrail reload, every turn) --------------------------
    def _role(msg):
        return msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)

    class GuardrailInjector(FrameProcessor):
        """Immediately before the LLM, rebuild the system prompt from brain + fresh guardrails.

        Fires on every LLMContextFrame - which the user aggregator emits both for normal turns and
        for the LLMRunFrame kickoff - so the very first (Envoy-opens) turn is already guardrail-aware.
        Runs unconditionally, even with zero guardrails, so the reload path is exercised from turn 1.
        """

        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, LLMContextFrame):
                ctx = frame.context
                guardrails = load_guardrails()  # fresh read of data/guardrails.json every turn
                transcript = [m for m in ctx.get_messages() if _role(m) != "system"]
                rebuilt = brain.build_messages(transcript, guardrails, constraints)
                # rebuilt[0] is the freshly-built system message; keep the running transcript intact.
                ctx.set_messages([rebuilt[0]] + transcript)
            await self.push_frame(frame, direction)

    guardrail_injector = GuardrailInjector()

    # --- Hook B: TurnEventObserver (real TurnEvents, wall-clock turn gap) -----------------------
    class TurnEventObserver(BaseObserver):
        """Emit a TurnEvent per spoken turn. latency_ms = wall-clock gap from the other party
        finishing to this party starting. counterpart = the human/restaurant (STT); envoy = the bot
        (TTS). The same frame is pushed once per hop, so we de-dupe by frame id."""

        def __init__(self, emit, **kwargs):
            super().__init__(**kwargs)
            self._emit_cb = emit
            self._seen = set()
            self._seen_order = deque(maxlen=8192)
            self._last_user_stop = None   # ns
            self._last_bot_stop = None    # ns
            self._pending_cp_latency = 0
            self._pending_envoy_latency = 0
            self._bot_speaking = False
            self._envoy_parts = []

        def _first_sight(self, frame):
            if frame.id in self._seen:
                return False
            self._seen.add(frame.id)
            self._seen_order.append(frame.id)
            if len(self._seen) > len(self._seen_order):
                self._seen = set(self._seen_order)
            return True

        @staticmethod
        def _gap_ms(start_ns, end_ns):
            if start_ns is None or end_ns is None or end_ns < start_ns:
                return 0
            return int((end_ns - start_ns) // 1_000_000)

        def _emit(self, speaker, text, latency_ms):
            try:
                self._emit_cb(TurnEvent(speaker=speaker, text=text, latency_ms=latency_ms))
            except Exception as e:  # never let dashboards break the call
                logger.warning(f"TurnEvent emit failed: {e}")

        async def on_push_frame(self, data: FramePushed):
            frame, ts = data.frame, data.timestamp

            if isinstance(frame, UserStartedSpeakingFrame):
                if not self._first_sight(frame):
                    return
                self._pending_cp_latency = self._gap_ms(self._last_bot_stop, ts)

            elif isinstance(frame, UserStoppedSpeakingFrame):
                if not self._first_sight(frame):
                    return
                self._last_user_stop = ts

            elif isinstance(frame, TranscriptionFrame):
                if not self._first_sight(frame):
                    return
                text = (getattr(frame, "text", "") or "").strip()
                if text:
                    self._emit("counterpart", text, self._pending_cp_latency)

            elif isinstance(frame, BotStartedSpeakingFrame):
                if not self._first_sight(frame):
                    return
                self._bot_speaking = True
                self._envoy_parts = []
                self._pending_envoy_latency = self._gap_ms(self._last_user_stop, ts)

            elif isinstance(frame, TTSTextFrame):
                if not self._first_sight(frame):
                    return
                if self._bot_speaking:
                    self._envoy_parts.append(getattr(frame, "text", "") or "")

            elif isinstance(frame, BotStoppedSpeakingFrame):
                if not self._first_sight(frame):
                    return
                self._bot_speaking = False
                text = "".join(self._envoy_parts).strip()
                if text:
                    self._emit("envoy", text, self._pending_envoy_latency)
                self._last_bot_stop = ts

    turn_observer = TurnEventObserver(on_event)

    # --- Pipeline assembly ---------------------------------------------------------------------
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            guardrail_injector,  # rebuild system prompt from brain + fresh guardrails, every turn
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=24000,
        ),
        observers=[turn_observer],
    )

    # --- Transport handlers: Envoy opens (first line generated by Nemotron, NOT hardcoded) ------
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected - Envoy opens: running the LLM on the system prompt alone")
        # Envoy speaks first. We add NO message to the context: the user aggregator's LLMRunFrame
        # handler emits an LLMContextFrame unconditionally, the GuardrailInjector sets the brain
        # system prompt, and Nemotron generates the opening line from SYSTEM_PROMPT + constraints.
        #
        # We deliberately do NOT seed a user-role "deliver your opening line" nudge. In the voice
        # transcript, user-role is the COUNTERPART, so the model treats such an instruction as
        # something the other party said - echoing it into its first spoken turn (the observed
        # "Hello, I'd like to make a Hello..." bug) and polluting the transcript for the whole call.
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await worker.cancel()

    return worker
