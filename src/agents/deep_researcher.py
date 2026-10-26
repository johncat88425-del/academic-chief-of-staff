"""Agent 3: Deep Researcher — 學術檢索專家。

Performs context-aware academic research anchored to course frameworks and rubric criteria.
Uses Google Search Grounding to guarantee verified, peer-reviewed, and real academic citations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agents.base import BaseAgent
from src.models import ResearchNote
from src.utils.llm import extract_json
from src.utils.prompts import DEEP_RESEARCHER_PROMPT

logger = logging.getLogger(__name__)


class DeepResearcherAgent(BaseAgent):
    """Academic research specialist that produces context-anchored findings."""

    def __init__(self, **kwargs):
        super().__init__(name="deep_researcher", **kwargs)

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        action = task.get("action", "")

        if action == "research_for_assignment":
            return await self._research_for_assignment(task)
        elif action == "find_sources":
            return await self._find_sources(task)

        return {"status": "error", "message": f"Unknown action: {action}"}

    async def _research_for_assignment(self, task: dict[str, Any]) -> dict[str, Any]:
        """Conduct targeted research for a specific assignment using real search grounding."""
        assignment_id = task.get("assignment_id", "")
        course_id = task.get("course_id", "")

        course = await self.db.get_course(course_id)
        if not course:
            return {"status": "error", "message": f"Course not found: {course_id}"}

        assignments = await self.db.get_assignments_by_course(course_id)
        assignment = next((a for a in assignments if a.id == assignment_id), None)
        if not assignment:
            return {"status": "error", "message": f"Assignment not found: {assignment_id}"}

        context_chunks = self.vectors.query(
            course_id=course_id,
            query_text=f"{assignment.title} {assignment.description}",
            n_results=5,
        )
        context_text = "\n---\n".join(c["content"] for c in context_chunks)

        prompt = f"""You are an elite academic literature researcher. Conduct rigorous academic research for this university assignment:

Course: {course.name} ({course.id})
Professor: {course.professor}
Theoretical Frameworks: {', '.join(course.theory_frameworks) or 'University Management / Academic frameworks'}
Professor Preferences: {course.professor_preferences}

Assignment Deliverable: {assignment.title}
Word / Time Limit: {assignment.word_limit or 'Not specified'}
Weight: {assignment.weight*100:.0f}% of course
Description & Instructions:
{assignment.description}

Rubric Criteria:
{json.dumps([r.model_dump() for r in assignment.rubric], indent=2, ensure_ascii=False)}

Course Material Excerpts:
{context_text}

TASK:
Find 3-5 REAL, peer-reviewed academic literature sources, seminal theoretical works, or case studies directly applicable to this assignment's questions and rubrics.
DO NOT fabricate citations. Use real authors and publications.

Return a JSON array of objects inside ```json ... ```:
[
  {{
    "title": "Exact Author(s) (Year) Title of Book/Journal Article",
    "summary": "Precise summary of the theoretical contribution or empirical finding",
    "relevance_rationale": "Explicit explanation of how to apply this to fulfill the rubric criteria of {assignment.title}",
    "key_quotes": "Notable quotes, core concepts, or analytical models to cite",
    "course_frameworks_linked": "Which specific course framework or concept this supports"
  }}
]
"""
        try:
            # 1. Try search grounded generation
            try:
                raw_response = await self.llm.generate_grounded(
                    prompt=prompt,
                    system_instruction=DEEP_RESEARCHER_PROMPT,
                    temperature=0.3,
                )
                notes_data = extract_json(raw_response)
            except Exception as ge:
                self.logger.warning(f"Grounded search failed ({ge}), falling back to direct JSON generation")
                raw_response = await self.llm.generate_json(
                    prompt=prompt,
                    system_instruction=DEEP_RESEARCHER_PROMPT,
                    temperature=0.3,
                )
                notes_data = extract_json(raw_response)

            if isinstance(notes_data, dict):
                notes_data = notes_data.get("research_notes", notes_data.get("notes", []))
            
            notes = []
            for i, nd in enumerate(notes_data):
                nd["id"] = f"{assignment_id}-note-{i+1}"
                nd["assignment_id"] = assignment_id
                notes.append(ResearchNote(**nd))

            self.logger.info(f"Generated {len(notes)} verified research notes for {assignment_id}")
            return {
                "status": "success",
                "notes": [n.model_dump() for n in notes],
            }

        except Exception as e:
            self.logger.error(f"Research failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _find_sources(self, task: dict[str, Any]) -> dict[str, Any]:
        """Find academic sources for a specific topic within a course context."""
        query = task.get("query", "")
        course_id = task.get("course_id", "")

        if not query:
            return {"status": "error", "message": "No query provided"}

        relevant = self.vectors.query(course_id=course_id, query_text=query, n_results=3)

        prompt = f"""Search for real, peer-reviewed academic literature related to:
Query: {query}
Course ID: {course_id}

Course Context:
{json.dumps(relevant, indent=2, default=str)}

Return a JSON array with 3 verified academic sources:
[
  {{
    "title": "Author(s) (Year) Title",
    "summary": "Key contribution",
    "relevance_rationale": "Why it matters for this topic"
  }}
]
"""
        try:
            try:
                raw = await self.llm.generate_grounded(prompt=prompt, system_instruction=DEEP_RESEARCHER_PROMPT)
                sources = extract_json(raw)
            except Exception:
                raw = await self.llm.generate_json(prompt=prompt, system_instruction=DEEP_RESEARCHER_PROMPT)
                sources = extract_json(raw)
            return {"status": "success", "sources": sources}
        except Exception as e:
            return {"status": "error", "message": str(e)}
