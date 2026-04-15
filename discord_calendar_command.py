#!/usr/bin/env python3
"""
Google Calendar Discord Command
Usage:
  python3 discord_calendar_command.py today
  python3 discord_calendar_command.py week
  python3 discord_calendar_command.py add "<title>" <YYYY-MM-DD> <HH:MM> [description] [location]
"""

import sys
import json
import os
from datetime import datetime, timedelta, timezone

# Paths
SECRETS_DIR = "/home/guy/.config/openclaw-secrets"
CLIENT_SECRET_FILE = f"{SECRETS_DIR}/google-calendar-client.json"
TOKEN_FILE = f"{SECRETS_DIR}/google-calendar-token.json"

# ── Google Calendar API ────────────────────────────────────────────────────────

def get_calendar_service():
    """Build an authorized Google Calendar service using stored credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    # Load client config for client_id/secret
    with open(CLIENT_SECRET_FILE) as f:
        client_config = json.load(f)
    
    client_id = client_config.get("client_id", "")
    client_secret = client_config.get("client_secret", "")

    creds = None

    # Load existing token (handles legacy format)
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            token_data = json.load(f)
        
        # Build Credentials from token data directly
        creds = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=token_data.get("scope", "").split()
        )

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token back
        with open(TOKEN_FILE, "w") as f:
            json.dump({
                "access_token": creds.token,
                "refresh_token": creds.refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": " ".join(creds.scopes or []),
                "token_type": "Bearer",
            }, f)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_config(
            client_config,
            ["https://www.googleapis.com/auth/calendar.readonly",
             "https://www.googleapis.com/auth/calendar.events"]
        )
        creds = flow.run_local_server(port=8878)

        # Save refreshed token
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def format_event(event):
    """Format a Google Calendar event for Discord display.
    Returns (time_str, end_str, title, location, description, is_all_day)
    """
    start = event.get("start", {})
    end = event.get("end", {})

    # Detect all-day event
    is_all_day = "date" in start and "dateTime" not in start

    if is_all_day:
        title = event.get("summary", "(No title)")
        return None, None, title, "", "", True

    # Get start time
    dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
    time_str = dt.strftime("%-I:%M %p")

    # Get end time
    if "dateTime" in end:
        dt_end = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
        end_str = dt_end.strftime("%-I:%M %p")
    else:
        end_str = None

    title = event.get("summary", "(No title)")
    location = event.get("location", "")
    description = event.get("description", "")

    return time_str, end_str, title, location, description, False


def get_today_events():
    """Fetch today's calendar events."""
    service = get_calendar_service()
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def get_week_events():
    """Fetch this week's calendar events (next 7 days)."""
    service = get_calendar_service()
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_day + timedelta(days=7)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_week.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def create_event(title, date_str, time_str, description="", location=""):
    """Create a Google Calendar event."""
    service = get_calendar_service()

    # Parse date and time
    date_part = datetime.strptime(date_str, "%Y-%m-%d")
    time_part = datetime.strptime(time_str, "%H:%M")

    start_dt = date_part.replace(
        hour=time_part.hour,
        minute=time_part.minute,
        second=0,
        microsecond=0,
        tzinfo=timezone.utc
    )
    end_dt = start_dt + timedelta(hours=1)

    event = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }

    created = service.events().insert(calendarId="primary", body=event).execute()
    return created.get("htmlLink", "")


# ── CLI Command Router ─────────────────────────────────────────────────────────

def cmd_today():
    """Handle !cal today"""
    events = get_today_events()
    if not events:
        return "📅 **Today** — No events scheduled."

    lines = ["📅 **Today's Schedule**\n"]
    for event in events:
        time_str, end_str, title, location, description, is_all_day = format_event(event)
        if is_all_day:
            lines.append(f"🎉 **{title}** — All day")
        else:
            if end_str:
                lines.append(f"🕐 **{time_str} – {end_str}** — {title}")
            else:
                lines.append(f"🕐 **{time_str}** — {title}")

    return "\n".join(lines)


def cmd_week():
    """Handle !cal week"""
    events = get_week_events()
    if not events:
        return "📅 **This Week** — No events scheduled."

    # Group by day
    by_day = {}
    for event in events:
        start = event.get("start", {})
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            day = dt.strftime("%A, %B %-d")
        elif "date" in start:
            dt = datetime.strptime(start["date"], "%Y-%m-%d")
            day = dt.strftime("%A, %B %-d")
        else:
            day = "Unknown"

        if day not in by_day:
            by_day[day] = []
        by_day[day].append(event)

    lines = ["📅 **This Week's Schedule**\n"]
    for day, day_events in by_day.items():
        lines.append(f"**{day}**")
        for event in day_events:
            time_str, end_str, title, location, description, is_all_day = format_event(event)
            if is_all_day:
                lines.append(f"  🎉 {title} — All day")
            else:
                if end_str:
                    lines.append(f"  🕐 {time_str} – {end_str} — {title}")
                else:
                    lines.append(f"  🕐 {time_str} — {title}")
        lines.append("")

    return "\n".join(lines).strip()


def cmd_add(args):
    """Handle !cal add"""
    # args: title | date | time | [description] | [location]
    if len(args) < 3:
        return ("**Usage:** `!cal add <title> | <YYYY-MM-DD> | <HH:MM> | [description] | [location]`\n"
                "Example: `!cal add Team standup | 2026-04-15 | 09:30 | Daily sync | Zoom`")

    title = args[0].strip('"')
    date_str = args[1].strip()
    time_str = args[2].strip()
    description = args[3].strip() if len(args) > 3 else ""
    location = args[4].strip() if len(args) > 4 else ""

    try:
        link = create_event(title, date_str, time_str, description, location)
        return (f"✅ **Event created:** {title}\n"
                f"📆 {date_str} at {time_str}\n"
                f"🔗 [View in Google Calendar]({link})")
    except Exception as e:
        return f"❌ Failed to create event: {e}"


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: discord_calendar_command.py <today|week|add> [args...]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "today":
        print(cmd_today())
    elif command == "week":
        print(cmd_week())
    elif command == "add":
        print(cmd_add(sys.argv[2:]))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
