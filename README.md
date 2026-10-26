# Academic Chief of Staff (智慧學業幕僚多代理系統)

An autonomous, multi-agent system that serves as your academic chief of staff —
managing deadlines, detecting conflicts, conducting research, and ensuring your
work aligns with grading rubrics.

## Features

- **Syllabus Parsing** — Ingest PDF/DOCX/TXT syllabi and auto-extract courses, assignments, rubrics
- **Conflict Detection** — Crunch Week Alerts when high-weight assignments overlap
- **Starter Packs** — Auto-generated research starter packs 7 days before deadlines
- **Rubric Critic** — Red-team review of drafts against grading criteria
- **Smart Scheduling** — Deep Work Blocks proposed in your real free time (Human-in-the-Loop)
- **Inbox Monitor** — Detect syllabus updates and deadline changes from school email

## Quick Start

```bash
# 1. Install dependencies
pip install -e .

# 2. Configure environment
cp .env.example .env
# Edit .env with your Gemini API key

# 3. Ingest a syllabus
python chief_of_staff.py ingest path/to/syllabus.pdf

# 4. Get your morning briefing
python chief_of_staff.py morning-brief
```
