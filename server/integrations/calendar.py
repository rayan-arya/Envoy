"""
integrations/calendar.py - REAL Google Calendar side effect. OWNER: Rayan.

create_event(booking) writes an actual event to the user's PRIMARY calendar and returns its id +
html link. No mocks, no fake success: every failure surfaces as {"ok": False, "error": ...} so the
caller can degrade gracefully. BookingResult carries only a spoken time (e.g. "7:00 PM"), so we
resolve the start to TODAY in the HOST machine's local timezone (a tz-aware datetime whose UTC
offset is embedded in the RFC3339 dateTime), default 90-minute duration. We deliberately do NOT read
the primary calendar's tz via calendars.get - that needs a broader scope than least-privilege
calendar.events; on the operator's own machine the host tz matches their calendar tz.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from contracts import BookingResult
from integrations.google_auth import AuthNotConfigured, build_calendar_service

DEFAULT_DURATION_MIN = 90


def _parse_time_today(time_str: str) -> datetime:
    """Resolve a bare spoken time ('7:00 PM', '7 pm', '19:00') to a tz-aware datetime TODAY in the
    host's local timezone (offset embedded). Raises ValueError if unparseable - never a silent guess.
    """
    now = datetime.now().astimezone()  # local tz with concrete UTC offset
    s = (time_str or "").strip().upper().replace(".", "")
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M", "%H"):
        try:
            t = datetime.strptime(s, fmt)
        except ValueError:
            continue
        return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    raise ValueError(f"could not parse reservation time {time_str!r}")


def create_event(booking: BookingResult) -> Dict[str, Any]:
    """Insert a real calendar event for a confirmed booking. Returns {event_id, html_link} on success."""
    try:
        svc = build_calendar_service()
    except AuthNotConfigured as e:
        return {"ok": False, "error": f"auth not configured: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"calendar auth/setup failed: {e}"}

    try:
        start = _parse_time_today(booking.time)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    end = start + timedelta(minutes=DEFAULT_DURATION_MIN)

    venue = booking.venue or "Reservation"
    desc_lines = [
        f"Party size: {booking.party_size}" if booking.party_size else None,
        f"Confirmation: {booking.confirmation_ref}" if booking.confirmation_ref else None,
        f"Estimated price: ${booking.price_estimate:.2f}" if booking.price_estimate else None,
        booking.notes or None,
        "Booked by Envoy.",
    ]
    body = {
        "summary": f"Dinner reservation - {venue}",
        "location": venue,
        "description": "\n".join(d for d in desc_lines if d),
        # dateTime carries the host's UTC offset; no explicit timeZone field needed for a one-off
        # event (avoids the calendars.get call that calendar.events scope can't make).
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    try:
        ev = svc.events().insert(calendarId="primary", body=body).execute()
        return {"ok": True, "event_id": ev.get("id"), "html_link": ev.get("htmlLink")}
    except Exception as e:
        return {"ok": False, "error": f"calendar insert failed: {e}"}
