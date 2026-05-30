"""
llm_client.py - thin text client for the NVIDIA Nemotron LLM (OpenAI-compatible /v1).
OWNER: Rayan. Both tracks import this. THIS IS THE PARALLELISM UNLOCK: it lets Rushil run
and test the entire brain + self-heal story in TEXT, with no voice pipeline.

Env (paste the event endpoints into .env):
  NEMOTRON_LLM_URL      e.g. http://nemotron-fleet-...elb.amazonaws.com/v1
  NEMOTRON_LLM_MODEL    e.g. nvidia/nemotron-3-super
  NEMOTRON_LLM_API_KEY  optional; matches the pipecat starter (falls back to NVIDIA_API_KEY).
  (fallback) OPENAI_API_KEY -> GPT-4.1, used only if NEMOTRON_LLM_URL is unset.

Requires: openai  (uv add openai)
"""
from __future__ import annotations
import os, json
from pathlib import Path
from typing import List, Dict, Optional, Any

# Auto-load server/.env at import so `uv run smoke_text.py` works without --env-file.
# Points at the .env next to this module, so it loads regardless of cwd. Does not override
# vars already set in the shell (standard load_dotenv behavior), keeping the OPENAI fallback intact.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

def _client_and_model():
    from openai import OpenAI
    url = os.getenv("NEMOTRON_LLM_URL", "").strip()
    if url:
        # NVIDIA endpoint is OpenAI-compatible; api_key is usually unchecked but required by the SDK.
        # Prefer NEMOTRON_LLM_API_KEY (matches the pipecat starter's bot-nemotron.py); fall back to
        # NVIDIA_API_KEY for back-compat, then a harmless placeholder vLLM ignores unless --api-key is set.
        api_key = os.getenv("NEMOTRON_LLM_API_KEY") or os.getenv("NVIDIA_API_KEY") or "not-needed"
        return OpenAI(base_url=url, api_key=api_key), os.getenv("NEMOTRON_LLM_MODEL", "nvidia/nemotron-3-super")
    # fallback so the team is never blocked if the Nemotron endpoint is down
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY", "")), "gpt-4.1"

def complete(messages: List[Dict[str, str]], tools: Optional[list] = None, temperature: float = 0.4) -> Dict[str, Any]:
    """Return {'text': str, 'tool_calls': list|None}."""
    client, model = _client_and_model()
    kwargs: Dict[str, Any] = dict(model=model, messages=messages, temperature=temperature)
    if tools:
        kwargs["tools"] = tools
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    return {"text": msg.content or "", "tool_calls": getattr(msg, "tool_calls", None)}

def complete_json(messages: List[Dict[str, str]], temperature: float = 0.2) -> Any:
    """For the monitor / patcher / parser: parse a JSON object/array, tolerating code fences."""
    raw = complete(messages, temperature=temperature)["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    try:
        return json.loads(raw)
    except Exception:
        # last resort: grab the outermost {...} or [...]
        for op, cl in (("{", "}"), ("[", "]")):
            if op in raw and cl in raw:
                try: return json.loads(raw[raw.index(op): raw.rindex(cl)+1])
                except Exception: pass
        return None
