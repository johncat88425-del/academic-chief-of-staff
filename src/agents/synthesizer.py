"""Agent 4: Synthesizer & Rubric Critic — 合成官與紅隊審查員。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agents.base import BaseAgent
from src.models import StarterPack, RubricCheckResult
from src.utils.llm import extract_json
from src.utils.prompts import SYNTHESIZER_PROMPT

console = Console()


class SynthesizerAgent(BaseAgent):
    """Synthesizes research and performs rubric-based quality checks."""

    def __init__(self, **kwargs):
        super().__init__(name="synthesizer", **kwargs)

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        action = task.get("action", "")

        handlers = {
            "generate_starter_pack": self._generate_starter_pack,
            "rubric_check": self._rubric_check,
            "generate_outline": self._generate_outline,
        }

        handler = handlers.get(action)
        if handler:
            return await handler(task)
        return {"status": "error", "message": f"Unknown action: {action}"}

    async def _generate_starter_pack(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a research starter pack for an upcoming assignment."""
        assignment_id = task.get("assignment_id", "")
        research_notes = task.get("research_notes", [])

        courses = await self.db.list_courses()
        assignment = None
        course = None
        for c in courses:
            assignments = await self.db.get_assignments_by_course(c.id)
            for a in assignments:
                if a.id == assignment_id:
                    assignment = a
                    course = c
                    break

        if not assignment or not course:
            return {"status": "error", "message": f"Assignment not found: {assignment_id}"}

        prompt = f"""Generate a comprehensive Starter Pack for this assignment:

Course: {course.name} ({course.id}) — Prof. {course.professor}
Assignment: {assignment.title}
Type: {assignment.assignment_type.value}
Due: {assignment.due_date.strftime('%Y-%m-%d')}
Weight: {assignment.weight*100:.0f}%
Description: {assignment.description}
Word Limit: {assignment.word_limit or 'Not specified'}
Citation Style: {assignment.citation_style or 'Not specified'}
Rubric: {json.dumps([r.model_dump() for r in assignment.rubric], indent=2)}
Special Instructions: {assignment.special_instructions}

Research Notes Available:
{json.dumps(research_notes, indent=2, default=str)}

Generate a JSON object with:
1. "requirement_breakdown": Clear breakdown of what the assignment asks (bullet points as string)
2. "rubric_landmines": List of common mistakes that lose points based on rubric analysis
3. "suggested_outline": A structured outline matching rubric criteria
4. "markdown_template": A ready-to-use Markdown template with section headers
"""
        try:
            response = await self.llm.generate_json(
                prompt=prompt,
                system_instruction=SYNTHESIZER_PROMPT,
                temperature=0.5,
            )
            pack_data = extract_json(response)

            starter_pack = StarterPack(
                assignment_id=assignment_id,
                assignment_title=assignment.title,
                course_id=course.id,
                due_date=assignment.due_date,
                requirement_breakdown=pack_data.get("requirement_breakdown", ""),
                rubric_landmines=pack_data.get("rubric_landmines", []),
                suggested_outline=pack_data.get("suggested_outline", ""),
                markdown_template=pack_data.get("markdown_template", ""),
            )

            console.print(Panel(
                f"{starter_pack.requirement_breakdown}\n\n"
                f"Rubric Landmines:\n" +
                "\n".join(f"  • {lm}" for lm in starter_pack.rubric_landmines) +
                f"\n\nSuggested Outline:\n{starter_pack.suggested_outline}",
                title=f"Starter Pack: {assignment.title}",
                border_style="green",
            ))

            return {
                "status": "success",
                "starter_pack": starter_pack.model_dump(),
            }

        except Exception as e:
            self.logger.error(f"Starter pack generation failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _rubric_check(self, task: dict[str, Any]) -> dict[str, Any]:
        """Perform rubric alignment check on a draft."""
        assignment_id = task.get("assignment_id", "")
        draft_text = task.get("draft", "")

        if not draft_text:
            return {"status": "error", "message": "No draft text provided"}

        courses = await self.db.list_courses()
        assignment = None
        for c in courses:
            assignments = await self.db.get_assignments_by_course(c.id)
            for a in assignments:
                if a.id == assignment_id:
                    assignment = a
                    break

        if not assignment:
            return {"status": "error", "message": f"Assignment not found: {assignment_id}"}

        if not assignment.rubric:
            return {"status": "error", "message": "No rubric available for this assignment"}

        prompt = f"""You are a STRICT Teaching Assistant reviewing a student's work.

Assignment: {assignment.title}
Word Limit: {assignment.word_limit or 'Not specified'}
Citation Style: {assignment.citation_style or 'Not specified'}
Special Instructions: {assignment.special_instructions}

Rubric Criteria:
{json.dumps([r.model_dump() for r in assignment.rubric], indent=2)}

Student's Draft:
---
{draft_text}
---

For EACH rubric criterion, output a JSON array of objects with:
- "criterion": The rubric criterion name
- "status": "met" | "partially_met" | "missing" | "unclear"
- "evidence": Quote from the draft that supports your assessment (or "Not found")
- "suggestion": Specific, actionable improvement suggestion

Also check:
- Word count compliance (actual vs limit)
- Citation format compliance
- Special instruction compliance

Be THOROUGH and UNFORGIVING.
"""
        try:
            response = await self.llm.generate_json(
                prompt=prompt,
                system_instruction=SYNTHESIZER_PROMPT,
                temperature=0.2,
            )
            checks_data = extract_json(response)
            if isinstance(checks_data, dict):
                checks_data = checks_data.get("checks", checks_data.get("results", []))

            results = [RubricCheckResult(assignment_id=assignment_id, **c) for c in checks_data]

            table = Table(title="Rubric Alignment Check")
            table.add_column("Criterion", style="white")
            table.add_column("Status", justify="center")
            table.add_column("Suggestion", style="dim")

            status_icons = {
                "met": "[green]Met[/]",
                "partially_met": "[yellow]Partial[/]",
                "missing": "[red]Missing[/]",
                "unclear": "[magenta]Unclear[/]",
            }

            for r in results:
                table.add_row(
                    r.criterion,
                    status_icons.get(r.status, r.status),
                    r.suggestion[:80] + "..." if len(r.suggestion) > 80 else r.suggestion,
                )
            console.print(table)

            return {
                "status": "success",
                "results": [r.model_dump() for r in results],
            }

        except Exception as e:
            self.logger.error(f"Rubric check failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _generate_outline(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate a structured outline for an assignment."""
        return await self._generate_starter_pack(task)
