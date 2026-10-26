"""Agent 1: Context Parser — 課綱與講義庫。

Parses syllabi and assessment briefs (PDF/DOCX/text) into structured Course and Assignment models.
Extracts both body paragraphs and table layouts (crucial for UK assessment briefs).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dateutil import parser as dt_parser

from src.agents.base import BaseAgent
from src.models import Course, Assignment, AssignmentType, RubricItem, DocumentChunk
from src.utils.llm import extract_json
from src.utils.prompts import CONTEXT_PARSER_PROMPT

logger = logging.getLogger(__name__)


def _normalize_assignment_type(raw: str) -> AssignmentType:
    val = (raw or "").lower()
    if any(k in val for k in ["essay", "reflective", "paper"]):
        return AssignmentType.ESSAY
    if any(k in val for k in ["presentation", "oral", "slide", "pitch"]):
        return AssignmentType.PRESENTATION
    if any(k in val for k in ["group", "team"]):
        return AssignmentType.GROUP_PROJECT
    if any(k in val for k in ["exam", "test", "midterm", "final"]):
        return AssignmentType.EXAM
    if any(k in val for k in ["quiz"]):
        return AssignmentType.QUIZ
    if any(k in val for k in ["report", "consultancy", "business report"]):
        return AssignmentType.ESSAY
    if any(k in val for k in ["lab"]):
        return AssignmentType.LAB_REPORT
    if any(k in val for k in ["problem", "exercise", "set"]):
        return AssignmentType.PROBLEM_SET
    if any(k in val for k in ["reading"]):
        return AssignmentType.READING_RESPONSE
    return AssignmentType.OTHER


def _parse_safe_date(raw_due: Any) -> datetime:
    if not raw_due:
        return datetime.now() + timedelta(days=30)
    if isinstance(raw_due, datetime):
        return raw_due
    s = str(raw_due).strip().replace("Z", "")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    try:
        return dt_parser.parse(s, fuzzy=True)
    except Exception:
        return datetime.now() + timedelta(days=30)


def _parse_safe_weight(raw_weight: Any) -> float:
    if raw_weight is None:
        return 0.0
    if isinstance(raw_weight, (int, float)):
        w = float(raw_weight)
        return w / 100.0 if w > 1.0 else w
    s = str(raw_weight).strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m:
        val = float(m.group(1))
        if val > 1.0 or "%" in s:
            return min(1.0, max(0.0, val / 100.0))
        return min(1.0, max(0.0, val))
    return 0.0


class ContextParserAgent(BaseAgent):
    """Parses academic documents into structured data."""

    def __init__(self, **kwargs):
        super().__init__(name="context_parser", **kwargs)

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        action = task.get("action", "")

        if action == "ingest_syllabus":
            return await self._ingest_syllabus(task)
        elif action == "parse_text":
            return await self._parse_text(task)
        
        return {"status": "error", "message": f"Unknown action: {action}"}

    async def _ingest_syllabus(self, task: dict[str, Any]) -> dict[str, Any]:
        """Read a syllabus file and extract course + assignment data."""
        file_path = Path(task.get("file_path", ""))
        
        if not file_path.exists():
            return {"status": "error", "message": f"File not found: {file_path}"}

        text = await self._extract_text(file_path)
        if not text:
            return {"status": "error", "message": f"Could not extract text from: {file_path}"}

        result = await self._parse_text({"text": text, "source": str(file_path)})
        
        if result.get("status") == "success" and result.get("course"):
            course = result["course"]

            # Filter out non-course files (guidelines, general FAQs, covers) with no assignments
            if len(course.assignments) == 0 and any(k in course.id.lower() for k in ["guidance", "faq", "ethics", "cover", "assessment_brie"]):
                return {
                    "status": "info",
                    "message": f"檔案《{file_path.name}》為學生指引或輔助文件，不含特定課程評分項目，已略過建立課程。",
                    "course": course,
                }

            # Save newly parsed assignments
            assignments_to_save = list(course.assignments)

            # Upsert or merge with existing course
            existing_course = await self.db.get_course(course.id)
            if existing_course:
                # Merge professor if existing was blank
                if not existing_course.professor and course.professor:
                    existing_course.professor = course.professor
                # Merge theory frameworks
                merged_frameworks = list(dict.fromkeys(existing_course.theory_frameworks + course.theory_frameworks))
                existing_course.theory_frameworks = merged_frameworks
                if course.professor_preferences:
                    if existing_course.professor_preferences:
                        existing_course.professor_preferences = f"{existing_course.professor_preferences}\n{course.professor_preferences}"
                    else:
                        existing_course.professor_preferences = course.professor_preferences
                await self.db.upsert_course(existing_course)
            else:
                await self.db.upsert_course(course)

            # Upsert each newly parsed assignment safely
            for assignment in assignments_to_save:
                await self.db.upsert_assignment(assignment)
            
            chunks = self._chunk_text(text, course.id, str(file_path))
            self.vectors.add_chunks(course.id, chunks)
            
            self.logger.info(f"Ingested syllabus for {course.id}: {len(course.assignments)} assignments")

        return result

    async def _parse_text(self, task: dict[str, Any]) -> dict[str, Any]:
        """Use Gemini to parse syllabus text into structured models with resilient schema mapping."""
        text = task.get("text", "")
        source_name = Path(task.get("source", "")).stem if task.get("source") else ""
        if not text:
            return {"status": "error", "message": "No text provided"}

        prompt = f"""You are an expert academic registrar parser. Parse the following university syllabus / assessment brief text into a structured JSON.

Document Name: {source_name}

Text content:
---
{text}
---

INSTRUCTIONS:
1. Identify the Course Code (e.g., MGT4019, MGT4009, MGT4003). If not found, use letters and digits from document name.
2. Identify Course Name and Course Coordinators / Professors.
3. Identify Theoretical Frameworks mentioned in the course or assignment (e.g. Gibbs Reflective Cycle, Argyris Double-loop Learning, Porter Five Forces, Dunning OLI, Uppsala Model).
4. Extract ALL assignments, deliverables, and assessment components.
   - For each assignment, extract title, description, assessment type (essay, presentation, group_project, exam, other), word limit or time limit (keep exact text, e.g. "1,000 words" or "20 minutes"), due date (ISO string or format like "2026-12-04 12:00"), weight (decimal 0.0-1.0, e.g. 0.3 for 30%), and the grading rubric items (criterion, max_points, description).
   - If the filename contains tags like "_1A_", "_1G_", "_1L_", include this in assignment ID (e.g. MGT4019-1A, MGT4009-1G).

OUTPUT JSON STRUCTURE ONLY:
{{
  "course": {{
    "id": "COURSE_CODE",
    "name": "Course Name",
    "professor": "Prof. Name",
    "semester": "2026-Fall",
    "theory_frameworks": ["Framework 1", "Framework 2"],
    "professor_preferences": "Guidance or notes...",
    "assignments": [
      {{
        "id": "COURSE_CODE-1A",
        "title": "Assignment Title",
        "description": "Full question prompt and guidance...",
        "assignment_type": "essay",
        "due_date": "2026-12-04T12:00:00",
        "weight": 0.3,
        "word_limit": "1,000 words",
        "citation_style": "Harvard / APA",
        "special_instructions": "Notes on GenAI, submission guidelines, etc.",
        "rubric": [
          {{
            "criterion": "Criterion title",
            "max_points": 10.0,
            "description": "Details of performance criteria..."
          }}
        ]
      }}
    ]
  }}
}}
"""
        try:
            raw_response = await self.llm.generate(
                prompt=prompt,
                system_instruction=CONTEXT_PARSER_PROMPT,
                temperature=0.2,
            )
            data = extract_json(raw_response)
            course_data = data.get("course", data)
            
            assignments_data = course_data.pop("assignments", []) if isinstance(course_data, dict) else []

            # Fallback course metadata
            raw_id = course_data.get("id", "")
            if not raw_id or raw_id == "COURSE_CODE":
                code_match = re.search(r"([A-Z]{3,4}\d{3,4}[A-Z]?)", source_name.upper())
                course_data["id"] = code_match.group(1) if code_match else (source_name[:15].replace(" ", "_") or "COURSE")
            
            if not course_data.get("name") or course_data.get("name") == "Course Name":
                course_data["name"] = course_data["id"]
            if not course_data.get("professor"):
                course_data["professor"] = ""
            if not course_data.get("semester"):
                course_data["semester"] = "2026-Fall"
            if not isinstance(course_data.get("theory_frameworks"), list):
                course_data["theory_frameworks"] = []

            course = Course(
                id=str(course_data["id"]).strip().replace(" ", "_"),
                name=str(course_data["name"]).strip(),
                professor=str(course_data.get("professor", "")).strip(),
                semester=str(course_data.get("semester", "2026-Fall")),
                theory_frameworks=[str(f).strip() for f in course_data["theory_frameworks"] if f],
                professor_preferences=str(course_data.get("professor_preferences", "")),
                assignments=[],
            )

            # Sanitize each assignment
            brief_match = re.search(r"_(1[A-Za-z0-9])_", source_name)
            brief_suffix = brief_match.group(1).upper() if brief_match else ""

            for idx, a_data in enumerate(assignments_data):
                if not isinstance(a_data, dict):
                    continue

                raw_aid = str(a_data.get("id", "")).strip()
                if not raw_aid or raw_aid == "COURSE_CODE-A1" or raw_aid == f"{course.id}-A1" or raw_aid == "COURSE_CODE-1A":
                    if brief_suffix:
                        raw_aid = f"{course.id}-{brief_suffix}"
                    else:
                        raw_aid = f"{course.id}-A{idx+1}"

                a_title = str(a_data.get("title", "")).strip() or f"{course.id} Deliverable {idx+1}"
                a_desc = str(a_data.get("description", "")).strip()
                a_type = _normalize_assignment_type(str(a_data.get("assignment_type", "")))
                a_weight = _parse_safe_weight(a_data.get("weight"))
                a_due = _parse_safe_date(a_data.get("due_date"))
                a_limit = str(a_data.get("word_limit", "")).strip() if a_data.get("word_limit") else None

                # Clean rubric
                rubric_items: list[RubricItem] = []
                for r in a_data.get("rubric", []):
                    if not isinstance(r, dict):
                        continue
                    crit = str(r.get("criterion", "")).strip()
                    if not crit:
                        continue
                    pts = r.get("max_points")
                    try:
                        pts_clean = float(pts) if pts is not None else 0.0
                    except Exception:
                        pts_clean = 0.0
                    rubric_items.append(RubricItem(
                        criterion=crit,
                        max_points=pts_clean,
                        description=str(r.get("description", "")).strip(),
                        common_pitfalls=r.get("common_pitfalls", []) if isinstance(r.get("common_pitfalls"), list) else [],
                    ))

                assignment = Assignment(
                    id=raw_aid,
                    course_id=course.id,
                    title=a_title,
                    description=a_desc,
                    assignment_type=a_type,
                    due_date=a_due,
                    weight=a_weight,
                    rubric=rubric_items,
                    word_limit=a_limit,
                    citation_style=str(a_data.get("citation_style", "")) or None,
                    special_instructions=str(a_data.get("special_instructions", "")),
                )
                course.assignments.append(assignment)
            
            return {"status": "success", "course": course}

        except Exception as e:
            self.logger.warning(f"LLM parsing failed ({e}), falling back to robust deterministic structural extractor...")
            fallback_course = self._deterministic_extract(text, source_name)
            if fallback_course:
                return {"status": "success", "course": fallback_course, "note": "Extracted via structural rule engine"}
            return {"status": "error", "message": f"Parsing failed: {e}"}

    def _deterministic_extract(self, text: str, source_name: str) -> Optional[Course]:
        """Robust zero-network fallback: parses UK University assessment briefs directly from text & tables."""
        try:
            # 1. Course Code
            course_id_m = re.search(r"\b([A-Z]{3,4}\d{3,4}[A-Za-z]?)\b", text)
            course_id = course_id_m.group(1).upper() if course_id_m else ""
            if not course_id:
                code_from_name = re.search(r"([A-Z]{3,4}\d{3,4}[A-Za-z]?)", source_name.upper())
                course_id = code_from_name.group(1) if code_from_name else source_name[:10].replace(" ", "_")

            # 2. Course Title
            title_m = re.search(r"Course [Tt]itle\s*[:|]?\s*([^\n|]+)", text)
            course_name = title_m.group(1).strip() if title_m else course_id

            # 3. Professor / Coordinator
            prof_m = re.search(r"Course Coordinator\s*[:|]?\s*([^\n|]+)", text)
            professor = prof_m.group(1).strip() if prof_m else ""

            # 4. Assignment details
            brief_match = re.search(r"_(1[A-Za-z0-9])_", source_name)
            brief_suffix = brief_match.group(1).upper() if brief_match else "A1"
            aid = f"{course_id}-{brief_suffix}"

            # Assignment Title / Method
            method_m = re.search(r"Assessment method\(s\)\s*[:|]?\s*([^\n|]+)", text, re.IGNORECASE)
            type_m = re.search(r"Type of assessment\s*[:|]?\s*([^\n|]+)", text, re.IGNORECASE)
            a_type_str = (method_m.group(1).strip() if method_m else "") or (type_m.group(1).strip() if type_m else "")
            
            # Submission date
            due_m = re.search(r"Submission date\s*[:|]?\s*([^\n|]+)", text, re.IGNORECASE)
            raw_due = due_m.group(1).strip() if due_m else ""
            a_due = _parse_safe_date(raw_due) if raw_due else datetime.now() + timedelta(days=30)

            # Weighting
            w_m = re.search(r"Weighting\s*[:|]?\s*(\d+)%", text, re.IGNORECASE)
            weight = (float(w_m.group(1)) / 100.0) if w_m else 0.5

            # Word limit
            limit_m = re.search(r"Assessment limit\s*[:|]?\s*([^\n|]+)", text, re.IGNORECASE)
            word_limit = limit_m.group(1).strip() if limit_m else ""

            # Activity description
            desc_m = re.search(r"Question/Description of Activity\s*[:|]?\s*([^\n]+)", text)
            desc = desc_m.group(1).strip() if desc_m else ""
            if not desc:
                # Fallback: grab first substantive paragraph after Assessment Information
                desc = "Assessment requirement extracted from course syllabus and assessment brief."

            course = Course(
                id=course_id,
                name=course_name,
                professor=professor,
                semester="2026-Fall",
                theory_frameworks=[],
                professor_preferences="",
                assignments=[
                    Assignment(
                        id=aid,
                        course_id=course_id,
                        title=f"{course_name} ({a_type_str or 'Assessment'})" if a_type_str else f"{course_id} Assignment {brief_suffix}",
                        description=desc,
                        assignment_type=_normalize_assignment_type(a_type_str or text[:200]),
                        due_date=a_due,
                        weight=weight,
                        rubric=[],
                        word_limit=word_limit or None,
                        citation_style="Harvard / APA",
                        special_instructions="Extracted from official assessment brief.",
                    )
                ]
            )
            return course
        except Exception as ex:
            self.logger.error(f"Deterministic extraction error: {ex}")
            return None

    async def _extract_text(self, file_path: Path) -> str:
        """Extract plain text from PDF, DOCX, or text files including tables."""
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            pages: list[str] = []
            for i, p in enumerate(reader.pages):
                txt = p.extract_text() or ""
                if txt.strip():
                    pages.append(f"--- [Page {i+1}] ---\n{txt}")
            return "\n\n".join(pages)

        elif suffix in (".docx", ".doc"):
            import docx
            doc = docx.Document(str(file_path))
            parts: list[str] = []

            # 1. Paragraphs
            for p in doc.paragraphs:
                t = p.text.strip()
                if t:
                    parts.append(t)

            # 2. Tables (CRITICAL: captures rubric, weights, deadlines, coordinators, limits)
            for t_idx, table in enumerate(doc.tables):
                parts.append(f"\n[Table {t_idx+1}]")
                for row in table.rows:
                    row_cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    # Deduplicate repeated text from merged cells in docx
                    deduped: list[str] = []
                    for c in row_cells:
                        if not deduped or c != deduped[-1]:
                            deduped.append(c)
                    if any(deduped):
                        parts.append(" | ".join(deduped))

            return "\n\n".join(parts)

        elif suffix in (".txt", ".md"):
            return file_path.read_text(encoding="utf-8")

        else:
            self.logger.warning(f"Unsupported file type: {suffix}")
            return ""

    def _chunk_text(
        self,
        text: str,
        course_id: str,
        source_file: str,
        chunk_size: int = 1000,
        overlap: int = 200,
    ) -> list[DocumentChunk]:
        """Split text into overlapping chunks for vector storage."""
        chunks = []
        start = 0
        idx = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            chunks.append(DocumentChunk(
                id=f"{course_id}-chunk-{idx}",
                course_id=course_id,
                source_file=source_file,
                content=chunk_text,
                chunk_index=idx,
            ))
            start += chunk_size - overlap
            idx += 1
        return chunks
