"""Outlook Calendar operations via Microsoft Graph API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

from src.models import TimeSlot, SlotSource
from src.outlook.auth import OutlookAuth

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookCalendar:
    """Read/write operations for Outlook Calendar via Graph API."""

    def __init__(self, auth: OutlookAuth):
        self._auth = auth

    async def get_events(
        self,
        start: datetime,
        end: datetime,
    ) -> list[TimeSlot]:
        """Fetch calendar events within a time range."""
        token = self._auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated. Run 'chief setup-outlook' first.")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GRAPH_BASE}/me/calendarview",
                params={
                    "startdatetime": start.isoformat(),
                    "enddatetime": end.isoformat(),
                    "$select": "subject,start,end,showAs",
                    "$orderby": "start/dateTime",
                    "$top": 100,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()

        slots = []
        for event in data.get("value", []):
            slots.append(TimeSlot(
                start=datetime.fromisoformat(event["start"]["dateTime"]),
                end=datetime.fromisoformat(event["end"]["dateTime"]),
                title=event.get("subject", ""),
                source=SlotSource.OUTLOOK,
                is_free=event.get("showAs", "") == "free",
            ))
        return slots

    async def create_event(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        body: str = "",
    ) -> Optional[str]:
        """Create a calendar event. Returns the event ID."""
        token = self._auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated.")

        event_data = {
            "subject": subject,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            "body": {"contentType": "text", "content": body},
            "showAs": "busy",
            "categories": ["Academic Chief of Staff"],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GRAPH_BASE}/me/events",
                json=event_data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            return response.json().get("id")

    async def delete_event(self, event_id: str) -> None:
        """Delete a calendar event by ID."""
        token = self._auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated.")

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{GRAPH_BASE}/me/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
