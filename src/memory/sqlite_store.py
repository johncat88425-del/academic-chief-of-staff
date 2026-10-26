"""SQLite-backed state store for assignments, schedules, and alerts.

使用 aiosqlite 實現非同步資料庫操作，儲存所有時程狀態與作業追蹤資料。
"""

from __future__ import annotations

import json
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite

from src.config import settings
from src.models import (
    Course, Assignment, SubTask, SubTaskStatus,
    DeepWorkBlock, ConflictAlert, Meeting,
)


class SQLiteStore:
    """Async SQLite store for persistent state management."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create all required tables."""
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                professor TEXT DEFAULT '',
                semester TEXT NOT NULL,
                theory_frameworks TEXT DEFAULT '[]',
                professor_preferences TEXT DEFAULT '',
                syllabus_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL REFERENCES courses(id),
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                assignment_type TEXT DEFAULT 'other',
                due_date TEXT NOT NULL,
                weight REAL DEFAULT 0.0,
                rubric TEXT DEFAULT '[]',
                word_limit INTEGER,
                citation_style TEXT,
                special_instructions TEXT DEFAULT '',
                starter_pack_generated INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subtasks (
                id TEXT PRIMARY KEY,
                assignment_id TEXT NOT NULL REFERENCES assignments(id),
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                "order" INTEGER NOT NULL,
                estimated_hours REAL DEFAULT 1.0,
                status TEXT DEFAULT 'not_started',
                scheduled_date TEXT,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS deep_work_blocks (
                id TEXT PRIMARY KEY,
                subtask_id TEXT NOT NULL REFERENCES subtasks(id),
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                staged INTEGER DEFAULT 1,
                confirmed INTEGER DEFAULT 0,
                outlook_event_id TEXT
            );

            CREATE TABLE IF NOT EXISTS conflict_alerts (
                id TEXT PRIMARY KEY,
                severity TEXT NOT NULL,
                week_start TEXT NOT NULL,
                conflicting_assignment_ids TEXT DEFAULT '[]',
                total_weight REAL DEFAULT 0.0,
                message TEXT NOT NULL,
                resolution_proposed TEXT DEFAULT '',
                acknowledged INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inbox_sync_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meetings (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                assignment_id TEXT,
                title TEXT NOT NULL,
                meeting_time TEXT NOT NULL,
                location TEXT DEFAULT '',
                topic_description TEXT DEFAULT '',
                brief_content TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS course_resources (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                title TEXT NOT NULL,
                resource_type TEXT DEFAULT 'paper',
                url_or_ref TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                relevance TEXT DEFAULT '',
                added_by TEXT DEFAULT 'ai',
                file_path TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sent_notifications (
                id TEXT PRIMARY KEY,
                event_key TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS focus_sessions (
                id TEXT PRIMARY KEY,
                assignment_id TEXT,
                duration_minutes INTEGER DEFAULT 25,
                notes TEXT DEFAULT '',
                completed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS timetable_slots (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                course_name TEXT DEFAULT '',
                day_of_week INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                classroom TEXT DEFAULT '',
                location TEXT DEFAULT '',
                class_type TEXT DEFAULT 'Lecture',
                professor TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );
        """)
        await self._db.commit()

        # Migrate course_resources to include file_path if not present
        try:
            await self._db.execute("ALTER TABLE course_resources ADD COLUMN file_path TEXT DEFAULT ''")
            await self._db.commit()
        except Exception:
            pass

        # Migrate meetings to include notes_file_path and notes_filename
        try:
            await self._db.execute("ALTER TABLE meetings ADD COLUMN notes_file_path TEXT DEFAULT ''")
            await self._db.commit()
        except Exception:
            pass

        try:
            await self._db.execute("ALTER TABLE meetings ADD COLUMN notes_filename TEXT DEFAULT ''")
            await self._db.commit()
        except Exception:
            pass

        try:
            await self._db.execute("ALTER TABLE meetings ADD COLUMN attachments TEXT DEFAULT '[]'")
            await self._db.commit()
        except Exception:
            pass

    async def upsert_course(self, course: Course) -> None:
        """Insert or update a course."""
        await self._db.execute(
            """INSERT INTO courses (id, name, professor, semester, theory_frameworks, professor_preferences, syllabus_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name, professor=excluded.professor,
                   theory_frameworks=excluded.theory_frameworks,
                   professor_preferences=excluded.professor_preferences,
                   syllabus_path=excluded.syllabus_path""",
            (course.id, course.name, course.professor, course.semester,
             json.dumps(course.theory_frameworks), course.professor_preferences,
             course.syllabus_path, course.created_at.isoformat())
        )
        await self._db.commit()

    async def get_course(self, course_id: str) -> Optional[Course]:
        """Retrieve a course by ID."""
        async with self._db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Course(
                id=row["id"], name=row["name"], professor=row["professor"],
                semester=row["semester"],
                theory_frameworks=json.loads(row["theory_frameworks"]),
                professor_preferences=row["professor_preferences"],
                syllabus_path=row["syllabus_path"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    async def list_courses(self) -> list[Course]:
        """List all courses."""
        courses = []
        async with self._db.execute("SELECT * FROM courses") as cursor:
            async for row in cursor:
                courses.append(Course(
                    id=row["id"], name=row["name"], professor=row["professor"],
                    semester=row["semester"],
                    theory_frameworks=json.loads(row["theory_frameworks"]),
                    professor_preferences=row["professor_preferences"],
                    syllabus_path=row["syllabus_path"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return courses

    async def upsert_assignment(self, assignment: Assignment) -> None:
        """Insert or update an assignment."""
        await self._db.execute(
            """INSERT INTO assignments (id, course_id, title, description, assignment_type,
                   due_date, weight, rubric, word_limit, citation_style,
                   special_instructions, starter_pack_generated, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title, description=excluded.description,
                   due_date=excluded.due_date, weight=excluded.weight,
                   rubric=excluded.rubric, word_limit=excluded.word_limit,
                   updated_at=excluded.updated_at""",
            (assignment.id, assignment.course_id, assignment.title, assignment.description,
             assignment.assignment_type.value, assignment.due_date.isoformat(),
             assignment.weight, json.dumps([r.model_dump() for r in assignment.rubric]),
             assignment.word_limit, assignment.citation_style,
             assignment.special_instructions, int(assignment.starter_pack_generated),
             assignment.created_at.isoformat(), assignment.updated_at.isoformat())
        )
        await self._db.commit()

    async def get_assignments_by_course(self, course_id: str) -> list[Assignment]:
        """Get all assignments for a course."""
        assignments = []
        async with self._db.execute(
            "SELECT * FROM assignments WHERE course_id = ? ORDER BY due_date", (course_id,)
        ) as cursor:
            async for row in cursor:
                assignments.append(self._row_to_assignment(row))
        return assignments

    async def get_upcoming_assignments(self, within_days: int = 30) -> list[Assignment]:
        """Get assignments due within N days, sorted by due date."""
        now = datetime.now().isoformat()
        cutoff = (datetime.now().replace(hour=23, minute=59) + timedelta(days=within_days)).isoformat()
        assignments = []
        async with self._db.execute(
            "SELECT * FROM assignments WHERE due_date >= ? AND due_date <= ? ORDER BY due_date",
            (now, cutoff)
        ) as cursor:
            async for row in cursor:
                assignments.append(self._row_to_assignment(row))
        return assignments

    def _row_to_assignment(self, row) -> Assignment:
        """Convert a database row to an Assignment model."""
        from src.models.course import RubricItem
        return Assignment(
            id=row["id"], course_id=row["course_id"], title=row["title"],
            description=row["description"], assignment_type=row["assignment_type"],
            due_date=datetime.fromisoformat(row["due_date"]),
            weight=row["weight"],
            rubric=[RubricItem(**r) for r in json.loads(row["rubric"])],
            word_limit=str(row["word_limit"]) if row["word_limit"] is not None else None,
            citation_style=row["citation_style"],
            special_instructions=row["special_instructions"],
            starter_pack_generated=bool(row["starter_pack_generated"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def upsert_subtask(self, subtask: SubTask) -> None:
        """Insert or update a subtask."""
        await self._db.execute(
            """INSERT INTO subtasks (id, assignment_id, title, description, "order",
                   estimated_hours, status, scheduled_date, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title, status=excluded.status,
                   scheduled_date=excluded.scheduled_date,
                   completed_at=excluded.completed_at""",
            (subtask.id, subtask.assignment_id, subtask.title, subtask.description,
             subtask.order, subtask.estimated_hours, subtask.status.value,
             subtask.scheduled_date.isoformat() if subtask.scheduled_date else None,
             subtask.completed_at.isoformat() if subtask.completed_at else None)
        )
        await self._db.commit()

    async def get_subtasks(self, assignment_id: str) -> list[SubTask]:
        """Get all subtasks for an assignment, ordered."""
        subtasks = []
        async with self._db.execute(
            'SELECT * FROM subtasks WHERE assignment_id = ? ORDER BY "order"',
            (assignment_id,)
        ) as cursor:
            async for row in cursor:
                subtasks.append(SubTask(
                    id=row["id"], assignment_id=row["assignment_id"],
                    title=row["title"], description=row["description"],
                    order=row["order"], estimated_hours=row["estimated_hours"],
                    status=row["status"],
                    scheduled_date=date.fromisoformat(row["scheduled_date"]) if row["scheduled_date"] else None,
                    completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
                ))
        return subtasks

    # ── Meeting CRUD ───────────────────────────────────────────

    async def upsert_meeting(self, meeting: Meeting) -> None:
        """Insert or update a scheduled meeting."""
        attachments_json = json.dumps([a.model_dump(mode="json") for a in meeting.attachments])
        await self._db.execute(
            """INSERT INTO meetings (id, course_id, assignment_id, title, meeting_time, location, topic_description, brief_content, notes_file_path, notes_filename, attachments, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title, meeting_time=excluded.meeting_time,
                   location=excluded.location, topic_description=excluded.topic_description,
                   brief_content=excluded.brief_content,
                   notes_file_path=excluded.notes_file_path,
                   notes_filename=excluded.notes_filename,
                   attachments=excluded.attachments""",
            (meeting.id, meeting.course_id, meeting.assignment_id, meeting.title,
             meeting.meeting_time.isoformat(), meeting.location,
             meeting.topic_description, meeting.brief_content,
             meeting.notes_file_path or "", meeting.notes_filename or "",
             attachments_json,
             meeting.created_at.isoformat())
        )
        await self._db.commit()

    async def list_meetings(self) -> list[Meeting]:
        """List all upcoming or past meetings sorted by time."""
        meetings = []
        async with self._db.execute("SELECT * FROM meetings ORDER BY meeting_time") as cursor:
            async for row in cursor:
                from src.models.schedule import MeetingFile
                row_keys = row.keys()
                att_raw = row["attachments"] if "attachments" in row_keys and row["attachments"] else "[]"
                try:
                    att_list = [MeetingFile(**it) for it in json.loads(att_raw)]
                except Exception:
                    att_list = []
                
                # Migrate legacy single note into attachments list if present
                legacy_path = row["notes_file_path"] if "notes_file_path" in row_keys else ""
                legacy_name = row["notes_filename"] if "notes_filename" in row_keys else ""
                if legacy_path and not att_list:
                    att_list.append(MeetingFile(
                        id=f"file-legacy",
                        filename=legacy_name or Path(legacy_path).name,
                        file_path=legacy_path,
                        uploaded_at=datetime.fromisoformat(row["created_at"]),
                    ))

                meetings.append(Meeting(
                    id=row["id"],
                    course_id=row["course_id"],
                    assignment_id=row["assignment_id"],
                    title=row["title"],
                    meeting_time=datetime.fromisoformat(row["meeting_time"]),
                    location=row["location"] or "線上/線下",
                    topic_description=row["topic_description"] or "",
                    brief_content=row["brief_content"] or "",
                    notes_file_path=legacy_path or "",
                    notes_filename=legacy_name or "",
                    attachments=att_list,
                    created_at=datetime.fromisoformat(row["created_at"]),
                ))
        return meetings

    async def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        """Get a single meeting by ID."""
        async with self._db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            from src.models.schedule import MeetingFile
            row_keys = row.keys()
            att_raw = row["attachments"] if "attachments" in row_keys and row["attachments"] else "[]"
            try:
                att_list = [MeetingFile(**it) for it in json.loads(att_raw)]
            except Exception:
                att_list = []

            legacy_path = row["notes_file_path"] if "notes_file_path" in row_keys else ""
            legacy_name = row["notes_filename"] if "notes_filename" in row_keys else ""
            if legacy_path and not att_list:
                att_list.append(MeetingFile(
                    id=f"file-legacy",
                    filename=legacy_name or Path(legacy_path).name,
                    file_path=legacy_path,
                    uploaded_at=datetime.fromisoformat(row["created_at"]),
                ))

            return Meeting(
                id=row["id"],
                course_id=row["course_id"],
                assignment_id=row["assignment_id"],
                title=row["title"],
                meeting_time=datetime.fromisoformat(row["meeting_time"]),
                location=row["location"] or "線上/線下",
                topic_description=row["topic_description"] or "",
                brief_content=row["brief_content"] or "",
                notes_file_path=legacy_path or "",
                notes_filename=legacy_name or "",
                attachments=att_list,
                created_at=datetime.fromisoformat(row["created_at"]),
            )

    async def delete_meeting(self, meeting_id: str) -> None:
        """Delete a meeting by ID."""
        await self._db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await self._db.commit()

    # ── Deletions ──────────────────────────────────────────────

    async def delete_course(self, course_id: str) -> None:
        """Cascade delete course, its assignments, subtasks and resources."""
        await self._db.execute("DELETE FROM subtasks WHERE assignment_id IN (SELECT id FROM assignments WHERE course_id = ?)", (course_id,))
        await self._db.execute("DELETE FROM assignments WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM course_resources WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM meetings WHERE course_id = ?", (course_id,))
        await self._db.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        await self._db.commit()

    async def update_assignment_due_date(self, assignment_id: str, new_due_date: str) -> None:
        """Update the due date of a specific assignment."""
        now_iso = datetime.now().isoformat()
        await self._db.execute(
            "UPDATE assignments SET due_date = ?, updated_at = ? WHERE id = ?",
            (new_due_date, now_iso, assignment_id)
        )
        await self._db.commit()

    async def delete_assignment(self, assignment_id: str) -> None:
        """Delete a single assignment and its subtasks."""
        await self._db.execute("DELETE FROM subtasks WHERE assignment_id = ?", (assignment_id,))
        await self._db.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
        await self._db.commit()

    # ── Course Resources ───────────────────────────────────────

    async def add_course_resource(self, resource: dict) -> None:
        """Add an extended resource (paper, reading, case study, link, or uploaded PDF)."""
        await self._db.execute(
            """INSERT INTO course_resources (id, course_id, title, resource_type, url_or_ref, summary, relevance, added_by, file_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title, summary=excluded.summary, relevance=excluded.relevance, file_path=excluded.file_path""",
            (resource["id"], resource["course_id"], resource["title"],
             resource.get("resource_type", "paper"), resource.get("url_or_ref", ""),
             resource.get("summary", ""), resource.get("relevance", ""),
             resource.get("added_by", "ai"), resource.get("file_path", ""),
             resource.get("created_at", datetime.now().isoformat()))
        )
        await self._db.commit()

    async def list_course_resources(self, course_id: str) -> list[dict]:
        """List all extended resources for a course."""
        resources = []
        async with self._db.execute("SELECT * FROM course_resources WHERE course_id = ? ORDER BY created_at DESC", (course_id,)) as cursor:
            async for row in cursor:
                resources.append({
                    "id": row["id"],
                    "course_id": row["course_id"],
                    "title": row["title"],
                    "resource_type": row["resource_type"],
                    "url_or_ref": row["url_or_ref"],
                    "summary": row["summary"],
                    "relevance": row["relevance"],
                    "added_by": row["added_by"],
                    "file_path": row["file_path"] if "file_path" in row.keys() else "",
                    "created_at": row["created_at"],
                })
        return resources

    async def get_course_resource(self, resource_id: str) -> Optional[dict]:
        """Get an extended resource by ID."""
        async with self._db.execute("SELECT * FROM course_resources WHERE id = ?", (resource_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "course_id": row["course_id"],
                "title": row["title"],
                "resource_type": row["resource_type"],
                "url_or_ref": row["url_or_ref"],
                "summary": row["summary"],
                "relevance": row["relevance"],
                "added_by": row["added_by"],
                "file_path": row["file_path"] if "file_path" in row.keys() else "",
                "created_at": row["created_at"],
            }

    async def delete_course_resource(self, resource_id: str) -> None:
        """Delete an extended resource by ID."""
        await self._db.execute("DELETE FROM course_resources WHERE id = ?", (resource_id,))
        await self._db.commit()

    async def is_notification_sent(self, event_key: str) -> bool:
        """Check if a specific alert/reminder has already been dispatched."""
        async with self._db.execute("SELECT 1 FROM sent_notifications WHERE event_key = ?", (event_key,)) as cur:
            row = await cur.fetchone()
            return row is not None

    async def mark_notification_sent(self, event_key: str) -> None:
        """Record that an alert has been dispatched to avoid duplicate spam."""
        import uuid
        nid = f"ntf-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        await self._db.execute(
            "INSERT INTO sent_notifications (id, event_key, sent_at) VALUES (?, ?, ?)",
            (nid, event_key, now)
        )
        await self._db.commit()

    async def get_setting(self, key: str, default: str = "") -> str:
        """Get persistent setting value."""
        async with self._db.execute("SELECT value FROM system_settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            if row:
                return row["value"]
            return default

    async def set_setting(self, key: str, value: str) -> None:
        """Set persistent setting value."""
        now = datetime.now().isoformat()
        await self._db.execute(
            """INSERT INTO system_settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, now)
        )
        await self._db.commit()

    async def add_timetable_slot(self, slot: dict) -> None:
        """Add a weekly class schedule slot."""
        await self._db.execute(
            """INSERT INTO timetable_slots
               (id, course_id, course_name, day_of_week, start_time, end_time, classroom, location, class_type, professor, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (slot["id"], slot["course_id"], slot.get("course_name", ""),
             slot["day_of_week"], slot["start_time"], slot["end_time"],
             slot.get("classroom", ""), slot.get("location", ""),
             slot.get("class_type", "Lecture"), slot.get("professor", ""),
             slot.get("created_at", datetime.now().isoformat()))
        )
        await self._db.commit()

    async def list_timetable_slots(self) -> list[dict]:
        """List all weekly class timetable slots ordered by day and start time."""
        slots = []
        async with self._db.execute(
            "SELECT * FROM timetable_slots ORDER BY day_of_week ASC, start_time ASC"
        ) as cur:
            async for row in cur:
                slots.append({
                    "id": row["id"],
                    "course_id": row["course_id"],
                    "course_name": row["course_name"],
                    "day_of_week": row["day_of_week"],
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                    "classroom": row["classroom"],
                    "location": row["location"],
                    "class_type": row["class_type"],
                    "professor": row["professor"],
                    "created_at": row["created_at"],
                })
        return slots

    async def delete_timetable_slot(self, slot_id: str) -> None:
        """Delete a timetable slot by ID."""
        await self._db.execute("DELETE FROM timetable_slots WHERE id = ?", (slot_id,))
        await self._db.commit()

    async def log_focus_session(self, assignment_id: str, duration_minutes: int = 25, notes: str = "") -> dict:
        """Log a completed focus / Pomodoro session."""
        import uuid
        sess_id = f"foc-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        await self._db.execute(
            """INSERT INTO focus_sessions (id, assignment_id, duration_minutes, notes, completed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (sess_id, assignment_id, duration_minutes, notes, now)
        )
        await self._db.commit()
        return {
            "id": sess_id,
            "assignment_id": assignment_id,
            "duration_minutes": duration_minutes,
            "notes": notes,
            "completed_at": now
        }

    async def get_focus_stats(self) -> dict:
        """Get aggregate focus hours and session counts."""
        async with self._db.execute("SELECT SUM(duration_minutes) as total_min, COUNT(*) as count FROM focus_sessions") as cursor:
            row = await cursor.fetchone()
            total_min = (row["total_min"] or 0) if row else 0
            count = (row["count"] or 0) if row else 0
            return {
                "total_minutes": total_min,
                "total_hours": round(total_min / 60, 1),
                "sessions_count": count
            }

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
