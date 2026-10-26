"""Data models for the knowledge base and research artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """A chunk of text from a course document, stored in the vector DB."""
    id: str
    course_id: str
    source_file: str
    content: str
    page_number: Optional[int] = None
    chunk_index: int = 0
    metadata: dict = Field(default_factory=dict)


class ResearchNote(BaseModel):
    """An external research finding anchored to a course context.
    
    緊扣課堂理論的外部文獻摘要，非空泛的通用 AI 廢話。
    """
    id: str
    assignment_id: str
    title: str
    source_url: str = ""
    authors: list[str] = Field(default_factory=list)
    summary: str
    relevance_rationale: str = Field(
        description="Why this source matters for THIS specific assignment and course framework"
    )
    key_quotes: list[str] = Field(default_factory=list)
    course_frameworks_linked: list[str] = Field(
        default_factory=list,
        description="Which course theoretical frameworks this note connects to"
    )
    created_at: datetime = Field(default_factory=datetime.now)


class RubricCheckResult(BaseModel):
    """Result of a rubric alignment check on a draft or outline.
    
    紅隊審查結果 — 嚴格助教視角的逐項比對。
    """
    assignment_id: str
    criterion: str
    status: str = Field(description="'met', 'partially_met', 'missing', 'unclear'")
    evidence: str = Field(description="Quote or reference from the draft that supports the status")
    suggestion: str = ""


class StarterPack(BaseModel):
    """Pre-assembled research starter pack for an upcoming assignment.
    
    開工彈藥包 — T-7 天自動備妥的研究起手式。
    """
    assignment_id: str
    assignment_title: str
    course_id: str
    due_date: datetime
    requirement_breakdown: str = Field(description="Structured breakdown of what the assignment asks")
    research_notes: list[ResearchNote] = Field(default_factory=list)
    rubric_landmines: list[str] = Field(
        default_factory=list,
        description="Common mistakes that lose points based on rubric analysis"
    )
    suggested_outline: str = ""
    markdown_template: str = ""
    generated_at: datetime = Field(default_factory=datetime.now)
