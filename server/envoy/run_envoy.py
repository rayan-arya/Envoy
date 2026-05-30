"""
run_envoy.py - run the Envoy brain as a REAL Pipecat voice agent over SmallWebRTC (browser).
OWNER: Rayan (Slice A.1). Twilio transport comes in A.3.

Usage (from server/):
    uv run python envoy/run_envoy.py            # serves the dev UI at http://localhost:7860
    uv run python envoy/run_envoy.py -t webrtc  # WebRTC only

Envoy is the CALLER acting on the user's behalf: it speaks first, then talks to whoever answers
(in the browser, that's you playing the restaurant). Real Nemotron LLM, real Gradium TTS, real
Nemotron STT - nothing stubbed. STT requires a reachable NVIDIA_ASR_URL in .env.
"""
import os
import sys
from pathlib import Path

# Make server/ importable whether launched as a script (sys.path[0] = envoy/) or a module.
_SERVER_DIR = Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from dotenv import load_dotenv  # noqa: E402
from loguru import logger  # noqa: E402

load_dotenv(_SERVER_DIR / ".env", override=True)

import brain  # noqa: E402
import pipeline_factory  # noqa: E402

# A.1 demo constraints: a real booking goal driving real inference (config, not a fake). Mirrors
# smoke_text.py. Real per-call constraints arrive in a later slice.
CONSTRAINTS = {
    "type": "dinner_reservation",
    "budget": 60,
    "party_size": 2,
    "time_window": {"preferred": "7:00 PM"},
    "shareable": ["reservation_name", "last_four"],
}


async def bot(runner_args):
    """Pipecat runner entry point. A.1 supports the SmallWebRTC (browser) transport only."""
    from pipecat.runner.types import SmallWebRTCRunnerArguments
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.workers.runner import WorkerRunner

    # Krisp noise filter is available when deployed to Pipecat Cloud (ENV != local).
    if os.environ.get("ENV") != "local":
        from pipecat.audio.filters.krisp_viva_filter import KrispVivaFilter

        krisp_filter = KrispVivaFilter()
    else:
        krisp_filter = None

    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        logger.error(
            f"A.1 supports SmallWebRTC only; got {type(runner_args).__name__}. Twilio lands in A.3."
        )
        return

    transport = SmallWebRTCTransport(
        webrtc_connection=runner_args.webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_in_filter=krisp_filter,
            audio_out_enabled=True,
        ),
    )

    worker = pipeline_factory.build_pipeline(
        system_prompt=brain.SYSTEM_PROMPT,
        tools=["end_call", "create_event", "send_confirmation"],
        transport=transport,
        constraints=CONSTRAINTS,
    )

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
