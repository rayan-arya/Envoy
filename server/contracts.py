"""
contracts.py - SINGLE SOURCE OF TRUTH for Envoy's data shapes + file paths.
OWNER: Rayan. LOCKED after the hour-0 review. If a shape must change, call a 5-min huddle.
Both tracks import from here. Stdlib only (no deps).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List
import json, os, time, pathlib

# ---- file paths (the cross-track state lives here) ----
DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
GUARDRAILS_PATH    = DATA_DIR / "guardrails.json"      # Rushil's patcher writes -> Rayan's pipeline reads
EVENTS_PATH        = DATA_DIR / "events.jsonl"         # Rayan's pipeline writes -> Rushil's dashboards read
EVAL_HISTORY_PATH  = DATA_DIR / "eval_history.json"    # Rushil's loop writes -> Rushil's dashboards read

# ---- shapes ----
@dataclass
class TimeWindow:
    earliest: Optional[str] = None
    latest: Optional[str] = None
    preferred: Optional[str] = None

@dataclass
class Constraint:
    type: str                                   # e.g. "dinner_reservation"
    time_window: TimeWindow
    party_size: int
    budget: float                               # hard ceiling
    hard_constraints: List[str] = field(default_factory=list)   # ["vegetarian","quiet"]
    prefs: List[str] = field(default_factory=list)
    shareable: List[str] = field(default_factory=lambda: ["reservation_name", "last_four"])

@dataclass
class Guardrail:
    id: str
    rule: str
    version: int
    added_after: Optional[str] = None           # the violation id that triggered it

@dataclass
class Violation:
    violation: bool
    type: Optional[str] = None                  # "credential_leak"|"constraint_violation"|"injection"
    evidence: str = ""
    severity: str = "low"                       # "low"|"medium"|"high"|"critical"

@dataclass
class BookingResult:
    success: bool
    venue: str = ""
    time: str = ""
    party_size: int = 0
    price_estimate: float = 0.0
    confirmation_ref: str = ""
    notes: str = ""

@dataclass
class TurnEvent:
    speaker: str                                # "envoy"|"counterpart"
    text: str
    latency_ms: int = 0
    ts: str = ""

@dataclass
class IterationRecord:
    iteration: int
    attack: str
    result_before: str                          # "BREACH"|"BLOCKED"
    guardrail_added: Optional[str]
    result_after: str                           # "BLOCKED"
    variant_result: str                         # "BLOCKED"
    trust_score: float

# ---- helpers (robust read/write; never crash the pipeline) ----
def _ensure():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not GUARDRAILS_PATH.exists():   GUARDRAILS_PATH.write_text("[]")
    if not EVAL_HISTORY_PATH.exists(): EVAL_HISTORY_PATH.write_text("[]")
    if not EVENTS_PATH.exists():       EVENTS_PATH.write_text("")

def load_guardrails() -> List[dict]:
    _ensure()
    try:
        return json.loads(GUARDRAILS_PATH.read_text() or "[]")
    except Exception:
        return []

def save_guardrails(rules: List[dict]) -> None:
    _ensure(); GUARDRAILS_PATH.write_text(json.dumps(rules, indent=2))

def append_guardrail(rule: str, added_after: Optional[str] = None) -> dict:
    rules = load_guardrails()
    g = {"id": f"R{len(rules)+1}", "rule": rule, "version": len(rules)+1, "added_after": added_after}
    rules.append(g); save_guardrails(rules); return g

def append_event(ev) -> None:
    _ensure()
    d = ev if isinstance(ev, dict) else asdict(ev)
    if not d.get("ts"): d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(EVENTS_PATH, "a") as f:
        f.write(json.dumps(d) + "\n")

def load_events() -> List[dict]:
    _ensure()
    out = []
    for line in EVENTS_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            try: out.append(json.loads(line))
            except Exception: pass
    return out

def append_iteration(rec) -> None:
    _ensure()
    d = rec if isinstance(rec, dict) else asdict(rec)
    hist = json.loads(EVAL_HISTORY_PATH.read_text() or "[]")
    hist.append(d); EVAL_HISTORY_PATH.write_text(json.dumps(hist, indent=2))

def load_iterations() -> List[dict]:
    _ensure()
    try: return json.loads(EVAL_HISTORY_PATH.read_text() or "[]")
    except Exception: return []
