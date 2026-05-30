"""
selfheal/replay_demo.py - deterministic Beat-4 REPLAY for the live dashboard. OWNER: Rushil.

Plays the REAL captured self-heal sequence back into the dashboard's data files, one step at a
time, so the existing dashboard (which diffs-before-render) animates each beat: the red BREACH
row appears, R1 flashes into Guardrails, trust climbs, the blocks fill in, and the Cekura panel
reveals last. It does NOT call the model - it replays the locked artifacts, so the money-shot
("The confirmation code is 551007") and the 0/5 -> 5/5 result are preserved exactly.

Flow (default, no flags):
  1. BACK UP the four live files to a temp dir.
  2. RESET them to a blank initial state (trust 50, no iterations, no rules, no cekura).
  3. REPLAY from the backup with a delay between steps (BREACH -> patch R1 -> BLOCKED ->
     iters 2-6 -> Cekura reveal).
  4. On completion OR any error/interrupt, RESTORE from the backup (try/finally) - the live
     files end byte-identical to where they started. Never leaves partial state.

Flags:
  --delay N      seconds between steps (default 2.5)
  --reset-only   back up, then blank the files (for a re-take); no replay, no restore
  --restore      restore the live files from the last backup and exit

Run (dashboard open at :8080):  python -m selfheal.replay_demo
"""
from __future__ import annotations
import os
import sys
import json
import time
import shutil
import argparse
import tempfile
from pathlib import Path

try:
    from contracts import GUARDRAILS_PATH, EVAL_HISTORY_PATH, DATA_DIR
except ModuleNotFoundError:  # allow `python selfheal/replay_demo.py` too
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from contracts import GUARDRAILS_PATH, EVAL_HISTORY_PATH, DATA_DIR

BEAT4_PATH = DATA_DIR / "beat4_transcripts.json"
CEKURA_PATH = Path(__file__).with_name("cekura_eval_results.json")
BACKUP_DIR = Path(tempfile.gettempdir()) / "envoy_replay_backup"

# logical name -> live path (order = restore order)
FILES = {
    "guardrails": GUARDRAILS_PATH,
    "eval_history": EVAL_HISTORY_PATH,
    "beat4": BEAT4_PATH,
    "cekura": CEKURA_PATH,
}


# --------------------------------------------------------------------------- #
# atomic IO (never let the dashboard read a half-written file)
# --------------------------------------------------------------------------- #
def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _write_json(path: Path, obj) -> None:
    _atomic_write(path, json.dumps(obj, indent=2))


# --------------------------------------------------------------------------- #
# backup / restore
# --------------------------------------------------------------------------- #
def _live_is_converged() -> bool:
    try:
        ev = json.loads(EVAL_HISTORY_PATH.read_text() or "[]")
        gr = json.loads(GUARDRAILS_PATH.read_text() or "[]")
        return len(ev) >= 1 and len(gr) >= 1
    except Exception:
        return False


def backup() -> None:
    """Snapshot the live files. Refuses to clobber a good backup with a blank live state."""
    if BACKUP_DIR.exists() and not _live_is_converged():
        print(f"  live state is blank and a backup already exists at {BACKUP_DIR} - keeping it "
              f"(not clobbering).", flush=True)
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for name, p in FILES.items():
        dst = BACKUP_DIR / (name + ".json")
        if p.exists():
            shutil.copy2(p, dst)
        else:
            dst.write_text("null")
    print(f"  backed up live files -> {BACKUP_DIR}", flush=True)


def restore() -> None:
    if not BACKUP_DIR.exists():
        print("  no backup found; nothing to restore.", flush=True)
        return
    for name, p in FILES.items():
        src = BACKUP_DIR / (name + ".json")
        if src.exists():
            shutil.copy2(src, p)
    print("  restored live files from backup (locked converged state).", flush=True)


def load_backup() -> dict:
    data = {}
    for name in FILES:
        src = BACKUP_DIR / (name + ".json")
        data[name] = json.loads(src.read_text() or "null") if src.exists() else None
    return data


def reset_blank() -> None:
    """Blank the four files so the dashboard shows the empty initial state.

    Note: cekura is reset to {} (not null) so the dashboard re-renders the blank state and hides
    the Cekura panel, rather than holding the last-good value via the server cache.
    """
    _write_json(GUARDRAILS_PATH, [])
    _write_json(EVAL_HISTORY_PATH, [])
    _write_json(BEAT4_PATH, [])
    _write_json(CEKURA_PATH, {})
    print("  reset: dashboard blank (trust 50, no iterations, no rules, Cekura hidden).", flush=True)


# --------------------------------------------------------------------------- #
# the replay
# --------------------------------------------------------------------------- #
def replay(data: dict, delay: float) -> None:
    iters = sorted(data["eval_history"], key=lambda r: r["iteration"])
    txs = data["beat4"]
    rails = data["guardrails"]
    cek = data["cekura"]
    tx_by_iter = {t["iteration"]: t for t in txs}

    rec1 = next(r for r in iters if r["iteration"] == 1)
    tx1 = tx_by_iter[1]
    leaked = (tx1.get("first_hit") or {}).get("leaked_value")

    n, total = 0, 3 + (len(iters) - 1) + 1
    def step(msg: str) -> None:
        nonlocal n
        n += 1
        print(f"  [{n}/{total}] {msg}", flush=True)
        time.sleep(delay)

    # (a) BREACH — the attack lands, secret leaks, trust still 50
    rec1_breach = {**rec1, "guardrail_added": None, "result_after": "BREACH",
                   "variant_result": "BREACH", "trust_score": 50}
    _write_json(EVAL_HISTORY_PATH, [rec1_breach])
    _write_json(BEAT4_PATH, [{**tx1, "patch": None}])     # no rule chip yet
    step(f"BREACH  · {rec1['attack']} · leaked {leaked} (red row appears, trust 50)")

    # (b) PATCH — R1 is written; it flashes into the Guardrails panel
    _write_json(GUARDRAILS_PATH, rails)
    rid = rails[0]["id"] if rails else "R1"
    step(f"PATCH   · {rid} written to guardrails.json (flashes in)")

    # (c) BLOCKED — same attack replayed, now blocked; trust bumps
    _write_json(EVAL_HISTORY_PATH, [rec1])                # full iter-1: BREACH->BLOCKED, variant BLOCKED
    _write_json(BEAT4_PATH, [tx1])                        # patch present -> "R1 added" chip
    step(f"BLOCKED · {rec1['attack']} replay blocked, variant blocked, trust -> {rec1['trust_score']}")

    # (d) iters 2..N — each blocked on first hit, trust climbing
    for k in range(2, len(iters) + 1):
        recs = iters[:k]
        cur_txs = [tx_by_iter[r["iteration"]] for r in recs]
        _write_json(EVAL_HISTORY_PATH, recs)
        _write_json(BEAT4_PATH, cur_txs)
        last = recs[-1]
        step(f"BLOCKED · iter {k} · {last['attack']} (variant {last['variant_result']}), "
             f"trust -> {last['trust_score']}")

    # (e) FINALE — the independent Cekura eval reveals
    _write_json(CEKURA_PATH, cek)
    step(f"CEKURA  · independent judge reveals "
         f"{cek.get('before_pass')}/{cek.get('before_total')} -> "
         f"{cek.get('after_pass')}/{cek.get('after_total')}")
    print("  converged.", flush=True)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Deterministic Beat-4 replay for the dashboard.")
    ap.add_argument("--delay", type=float, default=2.5, help="seconds between steps (default 2.5)")
    ap.add_argument("--reset-only", action="store_true", help="back up then blank the files; no replay")
    ap.add_argument("--restore", action="store_true", help="restore from the last backup and exit")
    args = ap.parse_args()

    if args.restore:
        restore()
        return

    if args.reset_only:
        backup()
        reset_blank()
        print("  files blanked. run with no flags to replay, or --restore to recover.", flush=True)
        return

    # default: backup -> reset -> replay -> (finally) restore
    print("ENVOY self-heal replay", flush=True)
    backup()
    data = load_backup()
    if not data.get("eval_history"):
        print("  ABORT: backup has no iterations - is the live state the locked converged one?",
              flush=True)
        return
    try:
        reset_blank()
        print(f"  replaying at {args.delay}s/step (open http://localhost:8080)...", flush=True)
        time.sleep(args.delay)                 # let the blank slate show first
        replay(data, args.delay)
    finally:
        restore()


if __name__ == "__main__":
    main()
