"""Data models for scheduling, time-blocking, and conflict detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SlotSource(str, Enum):
    """Where a calendar event originates."""
    OUTLOOK = "outlook"       # Synced from Outlook
    GENERATED = "generated"   # Created by this system
    MANUAL = "manual"         # User-specified


class TimeSlot(BaseModel):
    """A block of time on the calendar."""
    start: datetime
    end: datetime
    title: str = ""
    source: SlotSource = SlotSource.OUTLOOK
    is_free: bool = False

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


class DeepWorkBlock(BaseModel):
    """A scheduled focus session for a specific subtask.
    
    專注工作區塊 — 系統自動在真實空檔中安排的深度工作時段。
    """
    id: str
    subtask_id: str
    slot: TimeSlot
    staged: bool = True       # True = pending user confirmation (Human-in-the-Loop)
    confirmed: bool = False
    outlook_event_id: Optional[str] = None  # Set after writing to Outlook


class AlertSeverity(str, Enum):
    """Severity level for scheduling alerts."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"  # 地獄週預警 (Crunch Week Alert)


class ConflictAlert(BaseModel):
    """A detected scheduling conflict or crunch-week warning.
    
    撞期預警 — 當同一週有多門高比重作業截止時觸發。
    """
    id: str
    severity: AlertSeverity
    week_start: datetime
    conflicting_assignment_ids: list[str]
    total_weight: float = Field(description="Sum of assignment weights in the conflict window")
    message: str
    resolution_proposed: str = Field(
        default="",
        description="Auto-generated resolution, e.g. 'Move MGMT501-A2 prep forward by 7 days'"
    )
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=datetime.now)


class BackwardMilestone(BaseModel):
    """Milestone calculated by backward planning based on assignment weight & difficulty."""
    assignment_id: str
    phase_name: str
    target_date: datetime
    description: str
    days_before_due: int


class MeetingFile(BaseModel):
    """An attached file/note for a meeting."""
    id: str
    filename: str
    file_path: str
    uploaded_at: datetime = Field(default_factory=datetime.now)


class Meeting(BaseModel):
    """A scheduled meeting with AI-prepared briefing and agenda."""
    id: str
    course_id: str
    assignment_id: Optional[str] = None
    title: str
    meeting_time: datetime
    location: str = "Teams / Zoom / 線下討論"
    topic_description: str = ""
    brief_content: str = ""
    notes_file_path: Optional[str] = ""
    notes_filename: Optional[str] = ""
    attachments: list[MeetingFile] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)

