"""Data models for courses, assignments, and subtasks."""

from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AssignmentType(str, Enum):
    """Types of academic deliverables."""
    ESSAY = "essay"
    PROBLEM_SET = "problem_set"
    PRESENTATION = "presentation"
    GROUP_PROJECT = "group_project"
    EXAM = "exam"
    READING_RESPONSE = "reading_response"
    QUIZ = "quiz"
    LAB_REPORT = "lab_report"
    OTHER = "other"


class SubTaskStatus(str, Enum):
    """Lifecycle status of a subtask."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    SKIPPED = "skipped"


class SubTask(BaseModel):
    """A decomposed step within an assignment.
    
    例如：定題 → 文獻檢索 → 大綱 → 初稿 → 潤飾
    """
    id: str = Field(description="Unique subtask ID, e.g. 'MGMT501-A2-ST3'")
    assignment_id: str
    title: str
    description: str = ""
    order: int = Field(description="Execution order within the assignment")
    estimated_hours: float = Field(default=1.0, ge=0.25)
    status: SubTaskStatus = SubTaskStatus.NOT_STARTED
    scheduled_date: Optional[date] = None
    completed_at: Optional[datetime] = None


class RubricItem(BaseModel):
    """A single criterion from the grading rubric.
    
    評分標準中的單一評分項目，用於紅隊審查比對。
    """
    criterion: str = Field(description="e.g. 'Critical analysis using Porter's Five Forces'")
    max_points: Optional[float] = 0.0
    description: str = ""
    common_pitfalls: list[str] = Field(default_factory=list)


class Assignment(BaseModel):
    """A graded academic deliverable."""
    id: str = Field(description="Unique ID, e.g. 'MGMT501-A2'")
    course_id: str
    title: str
    description: str = ""
    assignment_type: AssignmentType = AssignmentType.OTHER
    due_date: Optional[datetime] = None
    weight: float = Field(default=0.0, description="Fraction of final grade, e.g. 0.25 = 25%")
    rubric: list[RubricItem] = Field(default_factory=list)
    subtasks: list[SubTask] = Field(default_factory=list)
    word_limit: Optional[str | int] = None
    citation_style: Optional[str] = None  # e.g. "APA 7th", "Chicago"
    special_instructions: str = ""
    starter_pack_generated: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Course(BaseModel):
    """A university course with its metadata."""
    id: str = Field(default="COURSE", description="Course code, e.g. 'MGMT501'")
    name: str = Field(default="Academic Module")
    professor: Optional[str] = ""
    semester: Optional[str] = "2026-Fall"
    theory_frameworks: list[str] = Field(
        default_factory=list,
        description="Key theoretical frameworks used in this course, e.g. ['Porter Five Forces', 'SWOT', 'PESTEL']"
    )
    professor_preferences: Optional[str] = ""
    syllabus_path: Optional[str] = None
    assignments: list[Assignment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
