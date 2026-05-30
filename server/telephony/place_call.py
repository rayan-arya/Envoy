"""
telephony/place_call.py - originate an OUTBOUND Twilio call so Envoy can phone the counterpart.
OWNER: Rayan (Slice A.3).

Twilio dials --to from TWILIO_FROM and connects the call's media stream (8 kHz mu-law) to the
RUNNING bot's /ws endpoint via <Connect><Stream wss://<public-host>/ws/>. The bot must be up and
publicly reachable - for the demo that's an ngrok tunnel to localhost:7860 - and you pass that
public host as --public-host (or PUBLIC_HOST env).

This is the outbound DEMO path. Cekura is a SEPARATE path (WebRTC via Pipecat Cloud) and is NOT
served by this dialer or by ngrok.

Usage (with the bot running behind ngrok):
    uv run python -m telephony.place_call --to +14155551234 --public-host abc123.ngrok.io
    uv run python -m telephony.place_call --to +14155551234 --public-host abc123.ngrok.io --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SERVER_DIR = Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_SERVER_DIR / ".env", override=True)


def _normalize_host(public_host: str) -> str:
    """Strip any scheme and trailing slash so we can build a clean wss:// URL."""
    host = public_host.strip().rstrip("/")
    for pre in ("https://", "http://", "wss://", "ws://"):
        if host.startswith(pre):
            host = host[len(pre):]
    return host


def build_twiml(public_host: str) -> str:
    """TwiML that bridges the call's audio to the bot's /ws media-stream endpoint."""
    host = _normalize_host(public_host)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="wss://{host}/ws" />'
        "</Connect></Response>"
    )


def place_call(to_number: str, public_host: str, from_number: str | None = None,
               dry_run: bool = False) -> str | None:
    """Originate the outbound call. Returns the Twilio call SID, or None on --dry-run."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = from_number or os.getenv("TWILIO_FROM")

    missing = [name for name, val in (
        ("TWILIO_ACCOUNT_SID", account_sid),
        ("TWILIO_AUTH_TOKEN", auth_token),
        ("TWILIO_FROM (or --from)", from_number),
    ) if not val]
    if missing:
        raise SystemExit(f"ERROR: missing required Twilio config: {', '.join(missing)}")

    twiml = build_twiml(public_host)
    print(f"  to     : {to_number}")
    print(f"  from   : {from_number}")
    print(f"  stream : wss://{_normalize_host(public_host)}/ws")
    print(f"  twiml  : {twiml}")

    if dry_run:
        print("  [dry-run] not placing the call.")
        return None

    from twilio.rest import Client

    client = Client(account_sid, auth_token)
    call = client.calls.create(to=to_number, from_=from_number, twiml=twiml)
    print(f"  call SID : {call.sid}")
    return call.sid


def main():
    p = argparse.ArgumentParser(description="Place an outbound Twilio call into the Envoy bot.")
    p.add_argument("--to", required=True, help="Destination number in E.164, e.g. +14155551234")
    p.add_argument("--public-host", default=os.getenv("PUBLIC_HOST", ""),
                   help="Public host of the running bot, e.g. abc123.ngrok.io. Defaults to PUBLIC_HOST env.")
    p.add_argument("--from", dest="from_number", default=None,
                   help="Twilio caller ID (E.164). Defaults to TWILIO_FROM env.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the TwiML + call params without placing a real call.")
    args = p.parse_args()
    if not args.public_host:
        raise SystemExit("ERROR: --public-host (or PUBLIC_HOST env) is required, e.g. abc123.ngrok.io")
    place_call(args.to, args.public_host, args.from_number, args.dry_run)


if __name__ == "__main__":
    main()
