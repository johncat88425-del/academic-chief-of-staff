"""Outlook Inbox delta monitor via Microsoft Graph API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import httpx

from src.outlook.auth import OutlookAuth

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

COURSE_KEYWORDS = [
    "syllabus", "assignment", "extension", "deadline",
    "due date", "rubric", "grade", "submission",
    "reading", "lecture", "exam", "quiz", "midterm", "final",
]


class OutlookInboxMonitor:
    """Monitors Outlook inbox for course-related email updates."""

    def __init__(self, auth: OutlookAuth):
        self._auth = auth
        self._delta_link: Optional[str] = None

    async def scan_recent(
        self,
        course_codes: list[str],
        hours_back: int = 24,
    ) -> list[dict]:
        """Scan recent emails for course-related content."""
        token = self._auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated. Run 'chief setup-outlook' first.")

        search_terms = course_codes + COURSE_KEYWORDS
        filter_query = " OR ".join(f'subject:{term}' for term in search_terms)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{GRAPH_BASE}/me/messages",
                params={
                    "$search": f'"{filter_query}"',
                    "$select": "subject,from,receivedDateTime,bodyPreview",
                    "$top": 20,
                    "$orderby": "receivedDateTime desc",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()

        results = []
        for msg in data.get("value", []):
            results.append({
                "subject": msg.get("subject", ""),
                "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "received": msg.get("receivedDateTime", ""),
                "preview": msg.get("bodyPreview", ""),
            })

        return results

    async def get_delta(
        self,
        course_codes: list[str],
    ) -> list[dict]:
        """Get new/changed messages since last check using delta query."""
        token = self._auth.get_access_token()
        if not token:
            raise RuntimeError("Not authenticated.")

        url = self._delta_link or f"{GRAPH_BASE}/me/mailFolders/inbox/messages/delta"

        all_messages = []
        async with httpx.AsyncClient() as client:
            while url:
                response = await client.get(
                    url,
                    params={"$select": "subject,from,receivedDateTime,bodyPreview"} if not self._delta_link else {},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                data = response.json()

                for msg in data.get("value", []):
                    subject = (msg.get("subject", "") or "").lower()
                    preview = (msg.get("bodyPreview", "") or "").lower()
                    combined = subject + " " + preview

                    if any(code.lower() in combined for code in course_codes) or                        any(kw in combined for kw in COURSE_KEYWORDS):
                        all_messages.append({
                            "subject": msg.get("subject", ""),
                            "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                            "received": msg.get("receivedDateTime", ""),
                            "preview": msg.get("bodyPreview", ""),
                        })

                url = data.get("@odata.nextLink")

            if "@odata.deltaLink" in data:
                self._delta_link = data["@odata.deltaLink"]

        return all_messages
