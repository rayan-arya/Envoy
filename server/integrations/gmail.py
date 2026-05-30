"""
integrations/gmail.py - REAL Gmail side effect. OWNER: Rayan.

send_confirmation(booking, event_link) sends an actual email to CONFIRM_TO (env; default
rayan.arya@gmail.com) from the authorized account and returns its message_id. No mocks: every
failure surfaces as {"ok": False, "error": ...}. When event_link is provided (chained after
create_event), the email includes the calendar link.
"""
from __future__ import annotations

import base64
import os
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

from contracts import BookingResult
from integrations.google_auth import AuthNotConfigured, build_gmail_service

DEFAULT_CONFIRM_TO = "rayan.arya@gmail.com"


def _build_body(booking: BookingResult, event_link: Optional[str]) -> str:
    lines = [
        "Your reservation is confirmed.",
        "",
        f"Venue: {booking.venue}" if booking.venue else None,
        f"Time: {booking.time}" if booking.time else None,
        f"Party size: {booking.party_size}" if booking.party_size else None,
        f"Confirmation: {booking.confirmation_ref}" if booking.confirmation_ref else None,
        f"Estimated price: ${booking.price_estimate:.2f}" if booking.price_estimate else None,
        f"Notes: {booking.notes}" if booking.notes else None,
    ]
    if event_link:
        lines += ["", f"Added to your calendar: {event_link}"]
    lines += ["", "- Envoy"]
    return "\n".join(line for line in lines if line is not None)


def send_confirmation(booking: BookingResult, event_link: Optional[str] = None) -> Dict[str, Any]:
    """Send a real confirmation email. Returns {message_id, to} on success."""
    try:
        svc = build_gmail_service()
    except AuthNotConfigured as e:
        return {"ok": False, "error": f"auth not configured: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"gmail auth/setup failed: {e}"}

    to_addr = os.getenv("CONFIRM_TO") or DEFAULT_CONFIRM_TO
    venue = booking.venue or "your reservation"
    msg = MIMEText(_build_body(booking, event_link))
    msg["To"] = to_addr
    msg["Subject"] = f"Reservation confirmed - {venue}"
    # userId="me" => Gmail sets From to the authorized account automatically.
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"ok": True, "message_id": sent.get("id"), "to": to_addr}
    except Exception as e:
        return {"ok": False, "error": f"gmail send failed: {e}"}
