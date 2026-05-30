"""brain/parser.py - intent + constraint parser. OWNER: Rushil. (stub)"""
from llm_client import complete_json

PARSER_PROMPT = (
    "Extract a structured Constraint from the user's spoken request. Output ONLY JSON with keys: "
    "type, time_window{earliest,latest,preferred}, party_size, budget, hard_constraints[], prefs[], shareable[]. "
    "Default shareable to ['reservation_name','last_four']. REQUEST: {request}"
)

def parse_constraint(request: str) -> dict:
    return complete_json([{"role": "user", "content": PARSER_PROMPT.format(request=request)}]) or {}
