"""Agent 2: Outlook Engine — 信箱與排程官。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from rich.console import Console
from rich.table import Table

from src.agents.base import BaseAgent
from src.models import TimeSlot, DeepWorkBlock, SlotSource
from src.utils.prompts import OUTLOOK_ENGINE_PROMPT

console = Console()


class OutlookEngineAgent(BaseAgent):
    """Manages Outlook calendar and inbox integration.
    
    Human-in-the-Loop: calendar writes are ALWAYS staged for preview.
    """

    def __init__(self, **kwargs):
        super().__init__(name="outlook_engine", **kwargs)
        self._staged_blocks: list[DeepWorkBlock] = []

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        action = task.get("action", "")

        handlers = {
            "fetch_free_slots": self._fetch_free_slots,
            "propose_deep_work": self._propose_deep_work,
            "confirm_staged": self._confirm_staged,
            "scan_inbox": self._scan_inbox,
            "list_staged": self._list_staged,
        }

        handler = handlers.get(action)
        if handler:
            return await handler(task)
        return {"status": "error", "message": f"Unknown action: {action}"}

    async def _fetch_free_slots(self, task: dict[str, Any]) -> dict[str, Any]:
        """Fetch free time slots from Outlook calendar."""
        start_date = task.get("start_date", datetime.now().isoformat())
        end_date = task.get("end_date", (datetime.now() + timedelta(days=7)).isoformat())

        self.logger.info(f"Fetching free slots from {start_date} to {end_date}")
        
        mock_slots = [
            TimeSlot(
                start=datetime.now().replace(hour=9, minute=0),
                end=datetime.now().replace(hour=11, minute=30),
                title="Free block",
                source=SlotSource.OUTLOOK,
                is_free=True,
            ),
            TimeSlot(
                start=datetime.now().replace(hour=14, minute=0),
                end=datetime.now().replace(hour=16, minute=0),
                title="Free block",
                source=SlotSource.OUTLOOK,
                is_free=True,
            ),
        ]

        return {
            "status": "success",
            "free_slots": [s.model_dump() for s in mock_slots],
            "note": "Using mock data. Connect Outlook via 'chief setup-outlook' to get real data.",
        }

    async def _propose_deep_work(self, task: dict[str, Any]) -> dict[str, Any]:
        """Propose deep work blocks for a subtask, staged for user confirmation."""
        subtask_id = task.get("subtask_id", "")
        duration_minutes = task.get("duration_minutes", 90)

        slots_result = await self._fetch_free_slots(task)
        free_slots = slots_result.get("free_slots", [])

        proposed = []
        for slot_data in free_slots:
            slot = TimeSlot(**slot_data)
            if slot.duration_minutes >= duration_minutes:
                block = DeepWorkBlock(
                    id=f"dwb-{uuid4().hex[:8]}",
                    subtask_id=subtask_id,
                    slot=TimeSlot(
                        start=slot.start,
                        end=slot.start + timedelta(minutes=duration_minutes),
                        title=f"Deep Work: {subtask_id}",
                        source=SlotSource.GENERATED,
                        is_free=False,
                    ),
                    staged=True,
                    confirmed=False,
                )
                proposed.append(block)
                self._staged_blocks.append(block)
                break

        if proposed:
            console.print(f"\nProposed {len(proposed)} deep work block(s) — awaiting confirmation:")
            for b in proposed:
                console.print(
                    f"   [{b.id}] {b.slot.start.strftime('%a %H:%M')} – "
                    f"{b.slot.end.strftime('%H:%M')} for {b.subtask_id}"
                )

        return {
            "status": "success",
            "proposed": [b.model_dump() for b in proposed],
            "message": "Run 'chief confirm-schedule' to write to Outlook.",
        }

    async def _confirm_staged(self, task: dict[str, Any]) -> dict[str, Any]:
        """Confirm and write staged deep work blocks to Outlook."""
        block_ids = task.get("block_ids", [])
        
        to_confirm = (
            [b for b in self._staged_blocks if b.id in block_ids]
            if block_ids
            else self._staged_blocks
        )

        confirmed = []
        for block in to_confirm:
            block.staged = False
            block.confirmed = True
            block.outlook_event_id = f"mock-event-{block.id}"
            confirmed.append(block)
            self.logger.info(f"Confirmed deep work block: {block.id}")

        self._staged_blocks = [b for b in self._staged_blocks if b.staged]

        return {
            "status": "success",
            "confirmed": [b.model_dump() for b in confirmed],
            "remaining_staged": len(self._staged_blocks),
        }

    async def _scan_inbox(self, task: dict[str, Any]) -> dict[str, Any]:
        """Scan Outlook inbox for course-related updates."""
        keywords = task.get("keywords", [
            "syllabus update", "extension", "assignment",
            "deadline", "due date change", "new reading",
        ])
        course_codes = task.get("course_codes", [])

        self.logger.info(f"Scanning inbox for keywords: {keywords}")
        
        return {
            "status": "success",
            "new_messages": [],
            "note": "Inbox scanning requires Outlook connection. Run 'chief setup-outlook' first.",
        }

    async def _list_staged(self, task: dict[str, Any]) -> dict[str, Any]:
        """List all staged (unconfirmed) deep work blocks."""
        if not self._staged_blocks:
            console.print("No staged events pending.")
            return {"status": "success", "staged": []}

        table = Table(title="Staged Deep Work Blocks (Pending Confirmation)")
        table.add_column("ID", style="cyan")
        table.add_column("Subtask", style="white")
        table.add_column("Time", style="yellow")

        for b in self._staged_blocks:
            table.add_row(
                b.id, b.subtask_id,
                f"{b.slot.start.strftime('%a %m/%d %H:%M')} – {b.slot.end.strftime('%H:%M')}",
            )
        console.print(table)

        return {"status": "success", "staged": [b.model_dump() for b in self._staged_blocks]}
