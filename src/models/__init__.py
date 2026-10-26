"""Pydantic data models for the Academic Chief of Staff system."""

from .course import (
    AssignmentType,
    SubTaskStatus,
    SubTask,
    RubricItem,
    Assignment,
    Course,
)
from .schedule import (
    SlotSource,
    TimeSlot,
    DeepWorkBlock,
    AlertSeverity,
    ConflictAlert,
    BackwardMilestone,
    Meeting,
)
from .knowledge import (
    DocumentChunk,
    ResearchNote,
    RubricCheckResult,
    StarterPack,
)

__all__ = [
    "AssignmentType", "SubTaskStatus", "SubTask", "RubricItem", "Assignment", "Course",
    "SlotSource", "TimeSlot", "DeepWorkBlock", "AlertSeverity", "ConflictAlert",
    "BackwardMilestone", "Meeting",
    "DocumentChunk", "ResearchNote", "RubricCheckResult", "StarterPack",
]
