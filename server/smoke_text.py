"""
smoke_text.py - Phase-0 proof that the TEXT path works (run after pasting endpoints into .env).
Runs a few turns of Envoy vs the counterpart using llm_client + brain + counterpart - NO voice.
This is what unblocks Rushil. Usage:  uv run smoke_text.py
"""
import os
from llm_client import complete
import brain
from counterpart.persona import counterpart_system

def main():
    if not os.getenv("NEMOTRON_LLM_URL") and not os.getenv("OPENAI_API_KEY"):
        print("Set NEMOTRON_LLM_URL (+ NEMOTRON_LLM_MODEL) or OPENAI_API_KEY in .env first."); return

    mode = "normal"   # try "hard" or "hostile" too
    constraints = {"type": "dinner_reservation", "budget": 60, "party_size": 2,
                   "time_window": {"preferred": "7:00 PM"},
                   "shareable": ["reservation_name", "last_four"]}

    envoy_tr = [{"role": "user", "content": "Goal: book dinner for 2 around 7pm tonight, under $60. Call the restaurant."}]
    cp_tr = []
    cp_sys = counterpart_system(mode)
    last = "(the restaurant line rings)"

    for turn in range(6):
        # Envoy speaks
        msgs = brain.build_messages(envoy_tr + [{"role": "user", "content": f"Restaurant said: {last}"}],
                                    constraints=constraints)
        envoy = complete(msgs)["text"].strip()
        print(f"\nENVOY: {envoy}")
        envoy_tr.append({"role": "assistant", "content": envoy})
        # Counterpart replies
        cp_tr = [{"role": "system", "content": cp_sys}] + \
                [{"role": "user", "content": f"Caller said: {envoy}"}]
        last = complete(cp_tr)["text"].strip()
        print(f"REST:  {last}")
        if "confirmed" in last.lower() or "booked" in last.lower():
            print("\n[booking confirmed]"); break

if __name__ == "__main__":
    main()
