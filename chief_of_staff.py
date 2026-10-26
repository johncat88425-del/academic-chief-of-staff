"""CLI entry point for the Academic Chief of Staff.

智慧學業幕僚 — 命令列介面
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from src.config import settings
from src.memory import SQLiteStore, VectorStore
from src.utils.llm import GeminiClient
from src.agents import (
    OrchestratorAgent,
    ContextParserAgent,
    OutlookEngineAgent,
    DeepResearcherAgent,
    SynthesizerAgent,
)

app = typer.Typer(
    name="chief",
    help="Academic Chief of Staff — 智慧學業幕僚多代理系統",
    rich_markup_mode="rich",
)
console = Console()


async def _build_system() -> OrchestratorAgent:
    """Initialize all agents and shared memory."""
    db = SQLiteStore()
    await db.initialize()

    vectors = VectorStore()
    vectors.initialize()

    llm = GeminiClient()

    shared = {"sqlite_store": db, "vector_store": vectors, "llm": llm}
    orchestrator = OrchestratorAgent(**shared)
    orchestrator.register_agent(ContextParserAgent(**shared))
    orchestrator.register_agent(OutlookEngineAgent(**shared))
    orchestrator.register_agent(DeepResearcherAgent(**shared))
    orchestrator.register_agent(SynthesizerAgent(**shared))

    return orchestrator


def _run(coro):
    """Run an async coroutine from sync context."""
    return asyncio.run(coro)


@app.command()
def morning_brief():
    """Generate your daily morning briefing."""
    async def _go():
        orch = await _build_system()
        await orch.execute({"action": "morning_brief"})
    _run(_go())


@app.command()
def ingest(syllabus_path: Path = typer.Argument(..., help="Path to syllabus file (PDF/DOCX/TXT)")):
    """Ingest a syllabus and extract course data."""
    if not syllabus_path.exists():
        console.print(f"[red]Error: File not found: {syllabus_path}[/]")
        raise typer.Exit(1)

    async def _go():
        orch = await _build_system()
        result = await orch.execute({
            "action": "ingest_syllabus",
            "file_path": str(syllabus_path.resolve()),
        })
        if result.get("status") == "success":
            course = result.get("course")
            if course:
                console.print(Panel(
                    f"Course: {course.name} ({course.id})\n"
                    f"Professor: {course.professor}\n"
                    f"Assignments: {len(course.assignments)}\n"
                    f"Frameworks: {', '.join(course.theory_frameworks)}",
                    title="Syllabus Ingested",
                    border_style="green",
                ))
        else:
            console.print(f"[red]Error: {result.get('message', 'Unknown error')}[/]")

    _run(_go())


@app.command()
def status():
    """Show current system status and upcoming deadlines."""
    async def _go():
        orch = await _build_system()
        courses = await orch.db.list_courses()
        if not courses:
            console.print("[yellow]No courses loaded yet. Run 'chief ingest <syllabus>' first.[/]")
            return

        for course in courses:
            assignments = await orch.db.get_assignments_by_course(course.id)
            console.print(f"\n[bold cyan]{course.name}[/] ({course.id}) — Prof. {course.professor}")
            console.print(f"  Frameworks: {', '.join(course.theory_frameworks)}")
            console.print(f"  Assignments: {len(assignments)}")
            for a in assignments:
                console.print(f"    • {a.title} — Due: {a.due_date.strftime('%Y-%m-%d')} — Weight: {a.weight*100:.0f}%")

    _run(_go())


@app.command()
def starter_pack(assignment_id: str = typer.Argument(..., help="Assignment ID, e.g. 'MGMT501-A2'")):
    """Generate a research starter pack for an assignment."""
    async def _go():
        orch = await _build_system()
        researcher = orch.sub_agents.get("deep_researcher")
        synthesizer = orch.sub_agents.get("synthesizer")

        if not researcher or not synthesizer:
            console.print("[red]Agents not properly initialized.[/]")
            return

        course_id = assignment_id.rsplit("-", 1)[0]
        
        console.print(f"Researching for {assignment_id}...")
        research = await researcher.execute({
            "action": "research_for_assignment",
            "assignment_id": assignment_id,
            "course_id": course_id,
        })

        if research.get("status") == "success":
            console.print("Generating starter pack...")
            await synthesizer.execute({
                "action": "generate_starter_pack",
                "assignment_id": assignment_id,
                "research_notes": research.get("notes", []),
            })
        else:
            console.print(f"[red]Research failed: {research.get('message')}[/]")

    _run(_go())


@app.command()
def rubric_check(
    assignment_id: str = typer.Argument(..., help="Assignment ID"),
    draft_file: Path = typer.Argument(..., help="Path to draft file"),
):
    """Run rubric alignment check on a draft."""
    if not draft_file.exists():
        console.print(f"[red]Error: File not found: {draft_file}[/]")
        raise typer.Exit(1)

    draft_text = draft_file.read_text(encoding="utf-8")

    async def _go():
        orch = await _build_system()
        synthesizer = orch.sub_agents.get("synthesizer")
        if not synthesizer:
            console.print("[red]Synthesizer agent not initialized.[/]")
            return

        await synthesizer.execute({
            "action": "rubric_check",
            "assignment_id": assignment_id,
            "draft": draft_text,
        })

    _run(_go())


@app.command()
def schedule_work(assignment_id: str = typer.Argument(..., help="Assignment ID")):
    """Propose deep work blocks for an assignment."""
    async def _go():
        orch = await _build_system()
        outlook = orch.sub_agents.get("outlook_engine")
        if not outlook:
            console.print("[red]Outlook Engine agent not initialized.[/]")
            return

        subtasks = await orch.db.get_subtasks(assignment_id)
        if not subtasks:
            console.print(f"[yellow]No subtasks found for {assignment_id}. Ingest syllabus first.[/]")
            return

        for st in subtasks:
            if st.status.value == "not_started":
                await outlook.execute({
                    "action": "propose_deep_work",
                    "subtask_id": st.id,
                    "duration_minutes": int(st.estimated_hours * 60),
                })

    _run(_go())


@app.command()
def confirm_schedule():
    """Confirm and write staged schedule to Outlook."""
    async def _go():
        orch = await _build_system()
        outlook = orch.sub_agents.get("outlook_engine")
        if not outlook:
            console.print("[red]Outlook Engine agent not initialized.[/]")
            return

        await outlook.execute({"action": "list_staged"})
        
        if typer.confirm("Write all staged events to Outlook?"):
            result = await outlook.execute({"action": "confirm_staged"})
            console.print(f"[green]Confirmed {len(result.get('confirmed', []))} events.[/]")

    _run(_go())


@app.command()
def scan_inbox():
    """Scan Outlook inbox for course-related updates."""
    async def _go():
        orch = await _build_system()
        outlook = orch.sub_agents.get("outlook_engine")
        if not outlook:
            console.print("[red]Outlook Engine agent not initialized.[/]")
            return

        courses = await orch.db.list_courses()
        course_codes = [c.id for c in courses]

        result = await outlook.execute({
            "action": "scan_inbox",
            "course_codes": course_codes,
        })

        messages = result.get("new_messages", [])
        if messages:
            console.print(f"\nFound {len(messages)} course-related emails:")
            for msg in messages:
                console.print(f"  • [{msg['received'][:10]}] {msg['subject']} — from {msg['from']}")
        else:
            console.print("[green]No new course-related emails.[/]")
            if result.get("note"):
                console.print(f"[dim]{result['note']}[/]")

    _run(_go())


@app.command()
def setup_outlook():
    """Set up Outlook integration (Azure AD authentication)."""
    console.print(Panel(
        "To connect your school Outlook account, you need an Azure AD app registration.\n\n"
        "1. Follow the guide in docs/azure_setup.md\n"
        "2. Copy your Client ID, Tenant ID, and Client Secret to .env\n"
        "3. Run this command again to authenticate\n",
        title="Outlook Setup",
        border_style="blue",
    ))

    from src.outlook.auth import OutlookAuth
    auth = OutlookAuth()

    if auth.is_authenticated():
        console.print("[green]Already authenticated with Outlook![/]")
    else:
        if not settings.azure_client_id:
            console.print("[red]Azure credentials not found in .env file.[/]")
            console.print("See docs/azure_setup.md for setup instructions.")
            raise typer.Exit(1)

        url = auth.get_auth_url()
        console.print(f"\nOpen this URL in your browser:\n[blue]{url}[/]\n")
        code = typer.prompt("Paste the authorization code")
        result = auth.acquire_token_by_code(code)

        if "access_token" in result:
            console.print("[green]Successfully authenticated![/]")
        else:
            console.print(f"[red]Authentication failed: {result.get('error_description', 'Unknown error')}[/]")


@app.command()
def full_scan():
    """Run a full system scan (brief + conflicts + starter packs)."""
    async def _go():
        orch = await _build_system()
        await orch.execute({"action": "full_scan"})
    _run(_go())


if __name__ == "__main__":
    app()
