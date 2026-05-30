"""
integrations/google_auth.py - shared Google OAuth for Calendar + Gmail side effects. OWNER: Rayan.

Least-privilege scopes (calendar.events + gmail.send). First run mints token.json via a one-time
browser consent; afterwards the token auto-refreshes. credentials.json + token.json are gitignored
and never committed.

One-time consent (run once, interactively, before the bot can write events/emails):
    uv run python -m integrations.google_auth

Heavy google imports are deferred INSIDE functions so `import integrations.*` stays light and never
fails when the google libs / credentials are absent (the running bot surfaces that as a clean
AuthNotConfigured tool error rather than crashing the call).
"""
from __future__ import annotations

from pathlib import Path

# Least-privilege: create calendar events + send mail. Nothing else.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.send",
]

_HERE = Path(__file__).resolve().parent          # server/integrations
_SERVER_DIR = _HERE.parent                        # server/
CREDENTIALS_PATH = _SERVER_DIR / "credentials.json"
TOKEN_PATH = _SERVER_DIR / "token.json"


class AuthNotConfigured(Exception):
    """No credentials.json, or no valid token obtainable without interactive consent."""


def get_credentials(allow_interactive: bool = False):
    """Return valid Google OAuth credentials, or raise AuthNotConfigured.

    - Loads token.json if present; refreshes silently when expired with a refresh_token.
    - With allow_interactive=True (the one-time CLI), runs the local-server consent from
      credentials.json. The running bot calls with allow_interactive=False, so a missing token
      surfaces as AuthNotConfigured (clean tool error) rather than blocking on a browser.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except Exception as e:
            raise AuthNotConfigured(f"token refresh failed: {e}") from e

    if not allow_interactive:
        raise AuthNotConfigured(
            f"no valid token.json at {TOKEN_PATH}; run "
            f"`uv run python -m integrations.google_auth` once to consent"
        )

    if not CREDENTIALS_PATH.exists():
        raise AuthNotConfigured(f"credentials.json not found at {CREDENTIALS_PATH}")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    return creds


def build_calendar_service(allow_interactive: bool = False):
    """Build the Calendar v3 client (raises AuthNotConfigured if not authorized)."""
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=get_credentials(allow_interactive), cache_discovery=False)


def build_gmail_service(allow_interactive: bool = False):
    """Build the Gmail v1 client (raises AuthNotConfigured if not authorized)."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=get_credentials(allow_interactive), cache_discovery=False)


def primary_timezone(allow_interactive: bool = False) -> str:
    """The primary calendar's default IANA timezone (e.g. 'America/Los_Angeles')."""
    svc = build_calendar_service(allow_interactive)
    cal = svc.calendars().get(calendarId="primary").execute()
    return cal.get("timeZone", "UTC")


if __name__ == "__main__":
    # One-time interactive consent: mints/refreshes server/token.json.
    print(f"Using credentials: {CREDENTIALS_PATH}")
    if not CREDENTIALS_PATH.exists():
        raise SystemExit(
            f"ERROR: credentials.json not found at {CREDENTIALS_PATH}. Place your Google OAuth "
            f"client (Desktop app type) there first."
        )
    get_credentials(allow_interactive=True)
    print(f"OK: token.json written to {TOKEN_PATH} (scopes: {', '.join(SCOPES)})")
