"""
dashboards/server.py - the Self-Heal / Trust Dashboard. OWNER: Rushil.

A filmable, read-only telemetry console for Beat 4. It reads the three files the self-heal loop
writes and renders the BREACH -> patch -> BLOCKED -> variant arc with a climbing trust score.

  GET /            -> the single-page dashboard (static/index.html)
  GET /api/state   -> {guardrails, iterations, transcripts}, re-read fresh every request so the
                      page reflects live writes from selfheal/loop.py.

Read-only: never writes the data files. Tolerates a file caught mid-write by serving the last
good copy it saw (in-memory cache), so a partial JSON read never blanks the screen.

Run:  python dashboards/server.py   ->   http://localhost:8080   (bot is on 7860, no conflict)
"""
from __future__ import annotations
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

DASH_DIR = Path(__file__).resolve().parent          # server/dashboards
DATA_DIR = DASH_DIR.parent / "data"                 # server/data
INDEX = DASH_DIR / "static" / "index.html"

GUARDRAILS_PATH  = DATA_DIR / "guardrails.json"
EVAL_PATH        = DATA_DIR / "eval_history.json"
TRANSCRIPTS_PATH = DATA_DIR / "beat4_transcripts.json"
CEKURA_PATH      = DASH_DIR.parent / "selfheal" / "cekura_eval_results.json"  # sponsor proof

app = FastAPI(title="Envoy Self-Heal Monitor")

# last-good cache so a mid-write file never blanks the dashboard
_cache: dict = {}


def _read(path: Path, default):
    try:
        val = json.loads(path.read_text() or "null")
        if val is None:
            return _cache.get(path, default)
        _cache[path] = val
        return val
    except Exception:
        return _cache.get(path, default)


# Never let the browser cache the page or the state — a stale cached index.html was serving an
# old (pre-blink-fix) build even after the code was corrected.
_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "Pragma": "no-cache"}


@app.get("/")
def index():
    return HTMLResponse(INDEX.read_text(), headers=_NO_CACHE)


@app.get("/api/state")
def state():
    return JSONResponse({
        "guardrails":  _read(GUARDRAILS_PATH, []),
        "iterations":  _read(EVAL_PATH, []),
        "transcripts": _read(TRANSCRIPTS_PATH, []),
        "cekura":      _read(CEKURA_PATH, None),
    }, headers=_NO_CACHE)


if __name__ == "__main__":
    print("\n  Envoy Self-Heal Monitor  ->  http://localhost:8080\n")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
