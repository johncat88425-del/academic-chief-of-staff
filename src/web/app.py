"""Web Dashboard Backend using FastAPI.

提供直覺的網頁圖形化介面，支援：
- 分頁式 UI/UX (儀表總覽、我的課程、每週課表、開會日程、手機推播、課綱上傳)
- 手機即時推播連線 (ntfy / Bark / Telegram) 與背景排程提醒
- 每週課表管理 (教室、時間、地點、課程)
- 可隨時關閉的浮動提示 (Dismissible alerts)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.memory import SQLiteStore, VectorStore
from src.utils.llm import GeminiClient, extract_json
from src.models import Meeting, Assignment, AssignmentType
from src.services.notifier import MobileNotifier, DEFAULT_NTFY_TOPIC
from src.services.reminder_service import ReminderService
from src.agents import (
    OrchestratorAgent,
    ContextParserAgent,
    OutlookEngineAgent,
    DeepResearcherAgent,
    SynthesizerAgent,
)

app = FastAPI(title="Academic Chief of Staff Web UI")

UPLOAD_DIR = Path("./data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

RESOURCE_DIR = Path("./data/resources")
RESOURCE_DIR.mkdir(parents=True, exist_ok=True)

_orch: OrchestratorAgent | None = None
_notifier: MobileNotifier | None = None
_reminder_service: ReminderService | None = None


async def get_orch() -> OrchestratorAgent:
    global _orch
    if _orch is None:
        db = SQLiteStore()
        await db.initialize()
        vectors = VectorStore()
        vectors.initialize()
        llm = GeminiClient()

        shared = {"sqlite_store": db, "vector_store": vectors, "llm": llm}
        _orch = OrchestratorAgent(**shared)
        _orch.register_agent(ContextParserAgent(**shared))
        _orch.register_agent(OutlookEngineAgent(**shared))
        _orch.register_agent(DeepResearcherAgent(**shared))
        _orch.register_agent(SynthesizerAgent(**shared))

        await _ensure_default_timetable(db)
    return _orch


async def get_notifier() -> MobileNotifier:
    global _notifier
    if _notifier is None:
        orch = await get_orch()
        topic = await orch.db.get_setting("ntfy_topic", default=DEFAULT_NTFY_TOPIC)
        bark = await orch.db.get_setting("bark_key", default="")
        tg_token = await orch.db.get_setting("telegram_token", default="")
        tg_chat = await orch.db.get_setting("telegram_chat_id", default="")
        _notifier = MobileNotifier(default_topic=topic, bark_key=bark, telegram_token=tg_token, telegram_chat_id=tg_chat)
    return _notifier


async def _ensure_default_timetable(db: SQLiteStore):
    # 使用者要求：未提供的課表維持為空（0），不自動預填虛擬時段
    pass


@app.on_event("startup")
async def on_startup():
    orch = await get_orch()
    notifier = await get_notifier()
    global _reminder_service
    _reminder_service = ReminderService(orch.db, notifier)
    _reminder_service.start()


@app.on_event("shutdown")
async def on_shutdown():
    global _reminder_service
    if _reminder_service:
        _reminder_service.stop()


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/mobile-input", response_class=HTMLResponse)
async def mobile_input():
    """手機端專屬填寫與連線頁面 (Mobile Companion PWA)"""
    html_path = Path(__file__).parent / "templates" / "mobile_input.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="mobile_input.html not found")
    return html_path.read_text(encoding="utf-8")


@app.get("/api/network-info")
async def get_network_info():
    """取得伺服器本機 IP 供手機 QR Code 配對"""
    import socket
    import subprocess
    local_ip = "127.0.0.1"
    try:
        res = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, timeout=2)
        ip = res.stdout.strip()
        if ip:
            local_ip = ip
    except Exception:
        pass
    if local_ip == "127.0.0.1":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"
    return {"status": "success", "ip": local_ip, "port": 8400, "mobile_url": f"http://{local_ip}:8400/mobile-input"}


@app.get("/api/dashboard")
async def get_dashboard():
    orch = await get_orch()
    courses = await orch.db.list_courses()
    
    courses_data = []
    backward_plans = {}
    for c in courses:
        assignments = await orch.db.get_assignments_by_course(c.id)
        for a in assignments:
            backward_plans[a.id] = orch.calculate_backward_plan(a)
        courses_data.append({
            "id": c.id,
            "name": c.name,
            "professor": c.professor,
            "semester": c.semester,
            "theory_frameworks": c.theory_frameworks,
            "professor_preferences": c.professor_preferences,
            "assignments": [a.model_dump() for a in assignments],
        })

    upcoming = await orch.db.get_upcoming_assignments(within_days=60)
    conflicts = await orch._detect_conflicts(upcoming)

    # Build rich conflict war room details
    assignment_map = {}
    for c_obj in courses_data:
        for a_dict in c_obj["assignments"]:
            assignment_map[a_dict["id"]] = {
                **a_dict,
                "course_name": c_obj["name"],
                "professor": c_obj["professor"],
                "kickoff": backward_plans.get(a_dict["id"], [{}])[0] if backward_plans.get(a_dict["id"]) else None,
            }

    conflicts_data = []
    for cf in conflicts:
        cf_dict = cf.model_dump()
        detailed_assignments = [
            assignment_map[aid] for aid in cf.conflicting_assignment_ids if aid in assignment_map
        ]
        detailed_assignments.sort(key=lambda x: x.get("weight", 0), reverse=True)
        cf_dict["assignments_detail"] = detailed_assignments
        heaviest = detailed_assignments[0] if detailed_assignments else None
        cf_dict["action_plan"] = {
            "top_priority": f"【優先完成佔分最高者】首要攻克《{heaviest['course_id']}：{heaviest['title']}》（佔分高達 {int(heaviest['weight']*100)}%）" if heaviest else "安排動工優先順序",
            "kickoff_advice": "請依據難度推算之動工日分批啟動，強烈建議每項作業間隔 3~5 天起步，切勿在最後一週同時開工。",
            "task_breakdown": "大綱定題 → 延伸資料庫權威文獻檢索 → 撰寫核心段落 → 截止前 48 小時使用紅隊審查掃描量表。",
            "group_vs_individual": "小組作業請儘早在『開會日程』安排討論；個人報告善用專注工作區塊深度寫作。",
        }
        conflicts_data.append(cf_dict)

    # 掃描信箱重要更新
    inbox_updates = []
    outlook = orch.sub_agents.get("outlook_engine")
    if outlook:
        res = await outlook.execute({"action": "scan_inbox", "course_codes": [c.id for c in courses]})
        inbox_updates = res.get("new_messages", [])

    meetings = await orch.db.list_meetings()
    timetable = await orch.db.list_timetable_slots()
    focus_stats = await orch.db.get_focus_stats()

    # 通知設定狀態
    topic = await orch.db.get_setting("ntfy_topic", default=DEFAULT_NTFY_TOPIC)

    return {
        "status": "success",
        "courses": courses_data,
        "upcoming": [a.model_dump() for a in upcoming],
        "conflicts": conflicts_data,
        "backward_plans": backward_plans,
        "inbox_updates": inbox_updates,
        "meetings": [m.model_dump() for m in meetings],
        "timetable": timetable,
        "focus_stats": focus_stats,
        "notification_settings": {
            "topic": topic,
            "web_url": f"https://ntfy.sh/{topic}",
            "qr_url": f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=https://ntfy.sh/{topic}",
        }
    }


# ==================== 專注番茄鐘 (POMODORO FOCUS) ====================

@app.post("/api/focus/log")
async def log_focus(
    assignment_id: str = Form(""),
    duration_minutes: int = Form(25),
    notes: str = Form(""),
):
    orch = await get_orch()
    result = await orch.db.log_focus_session(assignment_id, duration_minutes, notes)
    stats = await orch.db.get_focus_stats()
    return {"status": "success", "session": result, "focus_stats": stats}


@app.get("/api/focus/stats")
async def get_focus_stats_api():
    orch = await get_orch()
    stats = await orch.db.get_focus_stats()
    return {"status": "success", "stats": stats}


# ==================== 課表管理 (TIMETABLE) ====================

@app.get("/api/timetable")
async def list_timetable():
    orch = await get_orch()
    slots = await orch.db.list_timetable_slots()
    return {"status": "success", "slots": slots}


@app.post("/api/timetable")
async def add_timetable(
    course_id: str = Form(...),
    course_name: str = Form(""),
    day_of_week: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    classroom: str = Form(""),
    location: str = Form(""),
    class_type: str = Form("Lecture"),
    professor: str = Form(""),
):
    orch = await get_orch()
    slot_id = f"slot-{uuid.uuid4().hex[:8]}"
    slot = {
        "id": slot_id,
        "course_id": course_id,
        "course_name": course_name or course_id,
        "day_of_week": day_of_week,
        "start_time": start_time,
        "end_time": end_time,
        "classroom": classroom,
        "location": location,
        "class_type": class_type,
        "professor": professor,
        "created_at": datetime.now().isoformat(),
    }
    await orch.db.add_timetable_slot(slot)
    return {"status": "success", "slot": slot}


@app.delete("/api/timetable/{slot_id}")
async def delete_timetable(slot_id: str):
    orch = await get_orch()
    await orch.db.delete_timetable_slot(slot_id)
    return {"status": "success"}


# ==================== 手機推播管理 (NOTIFICATIONS) ====================

@app.get("/api/notifications/settings")
async def get_notification_settings():
    orch = await get_orch()
    topic = await orch.db.get_setting("ntfy_topic", default=DEFAULT_NTFY_TOPIC)
    bark = await orch.db.get_setting("bark_key", default="")
    tg_token = await orch.db.get_setting("telegram_token", default="")
    tg_chat = await orch.db.get_setting("telegram_chat_id", default="")
    return {
        "status": "success",
        "topic": topic,
        "ntfy_web_url": f"https://ntfy.sh/{topic}",
        "qr_url": f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=https://ntfy.sh/{topic}",
        "bark_key": bark,
        "telegram_token": tg_token,
        "telegram_chat_id": tg_chat,
    }


@app.post("/api/notifications/settings")
async def save_notification_settings(
    topic: str = Form(DEFAULT_NTFY_TOPIC),
    bark_key: str = Form(""),
    telegram_token: str = Form(""),
    telegram_chat_id: str = Form(""),
):
    orch = await get_orch()
    clean_topic = topic.strip().replace(" ", "_") or DEFAULT_NTFY_TOPIC
    await orch.db.set_setting("ntfy_topic", clean_topic)
    await orch.db.set_setting("bark_key", bark_key.strip())
    await orch.db.set_setting("telegram_token", telegram_token.strip())
    await orch.db.set_setting("telegram_chat_id", telegram_chat_id.strip())

    notifier = await get_notifier()
    notifier.default_topic = clean_topic
    notifier.bark_key = bark_key.strip()
    notifier.telegram_token = telegram_token.strip()
    notifier.telegram_chat_id = telegram_chat_id.strip()

    return {"status": "success", "message": "通知設定已更新"}


@app.post("/api/notifications/test")
async def test_notification():
    notifier = await get_notifier()
    res = await notifier.send(
        title="📱 智慧學業幕僚 — 手機配對成功！",
        message="恭喜！您的手機已與智慧學業幕僚成功連線。\n今後所有作業截止日、難度建議動工日、開會日程與每日晨間簡報都會自動推播提醒！",
        priority=4,
        tags=["mortar_board", "tada", "iphone"],
        click_url="http://127.0.0.1:8400",
    )
    return {"status": "success", "result": res}


@app.post("/api/notifications/push-briefing")
async def push_briefing_notification():
    orch = await get_orch()
    notifier = await get_notifier()
    upcoming = await orch.db.get_upcoming_assignments(within_days=14)
    meetings = await orch.db.list_meetings()
    
    msg_lines = [f"📅 今日日期：{date.today().strftime('%Y-%m-%d')}"]
    msg_lines.append(f"📋 未來 14 天待辦作業：{len(upcoming)} 項")
    for a in upcoming[:3]:
        days_left = (a.due_date - datetime.now()).days if a.due_date else 0
        msg_lines.append(f" • {a.course_id}: {a.title} ({days_left}天後截止, {int(a.weight*100)}%)")
    if meetings:
        msg_lines.append(f"🤝 今日/近期會議：{len(meetings)} 場")
        
    summary_text = "\n".join(msg_lines)
    res = await notifier.send(
        title="☀️【今日晨間學業速報】",
        message=summary_text,
        priority=3,
        tags=["sunny", "clipboard"],
    )
    return {"status": "success", "summary": summary_text, "result": res}


@app.post("/api/notifications/push-deadlines")
async def push_deadlines_notification():
    orch = await get_orch()
    notifier = await get_notifier()
    upcoming = await orch.db.get_upcoming_assignments(within_days=30)
    if not upcoming:
        msg = "近期 30 天內無即將截止之作業。"
    else:
        msg_lines = [f"🚨 近期截止作業清單 (共 {len(upcoming)} 項)："]
        for a in upcoming:
            days = (a.due_date - datetime.now()).days if a.due_date else 0
            msg_lines.append(f" • [{days}天後] {a.course_id} {a.title} ({int(a.weight*100)}%)")
        msg = "\n".join(msg_lines)

    res = await notifier.send(
        title="⏰【作業截止倒數速報】",
        message=msg,
        priority=4,
        tags=["alarm_clock", "warning"],
    )
    return {"status": "success", "message": msg, "result": res}


# ==================== 會議日程 (MEETINGS) ====================

MEETING_FILES_DIR = Path("./data/meeting_notes")
MEETING_FILES_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/api/meetings")
async def list_meetings():
    orch = await get_orch()
    meetings = await orch.db.list_meetings()
    return {"status": "success", "meetings": [m.model_dump() for m in meetings]}


@app.post("/api/meetings")
async def create_meeting(
    course_id: str = Form(...),
    assignment_id: str = Form(""),
    title: str = Form(...),
    meeting_time: str = Form(...),
    location: str = Form("線上 / 校園討論"),
    topic_description: str = Form(""),
    notes_files: List[UploadFile] = File([]),
):
    orch = await get_orch()

    attachments: list[MeetingFile] = []
    combined_notes_texts = []

    # 1. 支援批次多檔案上傳 (PDF, Word DOCX, TXT, Slides)
    if notes_files:
        meeting_dir = MEETING_FILES_DIR / course_id
        meeting_dir.mkdir(parents=True, exist_ok=True)

        for nf in notes_files:
            if not nf.filename:
                continue
            dest = meeting_dir / f"{int(datetime.now().timestamp())}_{nf.filename}"
            with open(dest, "wb") as buffer:
                shutil.copyfileobj(nf.file, buffer)
            
            att_item = MeetingFile(
                id=f"file-{uuid.uuid4().hex[:8]}",
                filename=nf.filename,
                file_path=str(dest.resolve()),
                uploaded_at=datetime.now(),
            )
            attachments.append(att_item)

            # 萃取內文並加入向量資料庫
            suffix = dest.suffix.lower()
            text_extracted = ""
            if suffix == ".pdf":
                try:
                    from pypdf import PdfReader
                    r = PdfReader(str(dest))
                    text_extracted = "\n".join(p.extract_text() or "" for p in r.pages)
                except Exception:
                    pass
            elif suffix in (".docx", ".doc"):
                try:
                    import docx
                    d = docx.Document(str(dest))
                    text_extracted = "\n".join(p.text for p in d.paragraphs if p.text.strip())
                except Exception:
                    pass
            elif suffix in (".txt", ".md"):
                try:
                    text_extracted = dest.read_text(encoding="utf-8")
                except Exception:
                    pass

            if text_extracted.strip():
                combined_notes_texts.append(f"【檔案《{nf.filename}》內容摘要】：\n{text_extracted[:1200]}")
                parser = orch.sub_agents.get("context_parser")
                if parser:
                    chunks = parser._chunk_text(text_extracted, course_id, str(dest))
                    orch.vectors.add_chunks(course_id, chunks)

    # 2. 結合所有上傳之筆記內容，讓 AI 自動生成深度開會手冊
    combined_topic = topic_description or title
    if combined_notes_texts:
        combined_topic += "\n\n" + "\n\n".join(combined_notes_texts)

    brief_res = await orch._prepare_meeting_brief({
        "course_id": course_id,
        "assignment_id": assignment_id,
        "topic": combined_topic,
        "meeting_time": meeting_time,
    })
    brief_content = brief_res.get("brief_content", "")

    # 相容舊版單一欄位，若有多筆則取第一筆作為預設
    primary_path = attachments[0].file_path if attachments else ""
    primary_name = attachments[0].filename if attachments else ""

    meeting = Meeting(
        id=f"mtg-{uuid.uuid4().hex[:8]}",
        course_id=course_id,
        assignment_id=assignment_id or None,
        title=title,
        meeting_time=datetime.fromisoformat(meeting_time),
        location=location,
        topic_description=topic_description,
        brief_content=brief_content,
        notes_file_path=primary_path,
        notes_filename=primary_name,
        attachments=attachments,
    )

    await orch.db.upsert_meeting(meeting)
    return {"status": "success", "meeting": meeting.model_dump(mode="json")}


@app.post("/api/meetings/{meeting_id}/upload-notes")
async def upload_meeting_notes(
    meeting_id: str,
    notes_files: List[UploadFile] = File(...),
):
    """為既有的開會日程批次補上傳會議筆記或討論講義檔案。"""
    orch = await get_orch()
    meeting = await orch.db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    meeting_dir = MEETING_FILES_DIR / meeting.course_id
    meeting_dir.mkdir(parents=True, exist_ok=True)

    for nf in notes_files:
        if not nf.filename:
            continue
        dest = meeting_dir / f"{int(datetime.now().timestamp())}_{nf.filename}"
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(nf.file, buffer)

        att_item = MeetingFile(
            id=f"file-{uuid.uuid4().hex[:8]}",
            filename=nf.filename,
            file_path=str(dest.resolve()),
            uploaded_at=datetime.now(),
        )
        meeting.attachments.append(att_item)

        # 萃取內文並加入向量資料庫
        suffix = dest.suffix.lower()
        extracted_text = ""
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
                r = PdfReader(str(dest))
                extracted_text = "\n".join(p.extract_text() or "" for p in r.pages)
            except Exception:
                pass
        elif suffix in (".docx", ".doc"):
            try:
                import docx
                d = docx.Document(str(dest))
                extracted_text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
            except Exception:
                pass
        elif suffix in (".txt", ".md"):
            try:
                extracted_text = dest.read_text(encoding="utf-8")
            except Exception:
                pass

        if extracted_text.strip():
            parser = orch.sub_agents.get("context_parser")
            if parser:
                chunks = parser._chunk_text(extracted_text, meeting.course_id, str(dest))
                orch.vectors.add_chunks(meeting.course_id, chunks)

    # 同步 primary 檔名與路徑
    if meeting.attachments and not meeting.notes_file_path:
        meeting.notes_file_path = meeting.attachments[0].file_path
        meeting.notes_filename = meeting.attachments[0].filename

    await orch.db.upsert_meeting(meeting)
    return {"status": "success", "meeting": meeting.model_dump(mode="json")}


@app.get("/api/meetings/{meeting_id}/files/{file_id}")
async def download_meeting_file_by_id(meeting_id: str, file_id: str):
    """下載指定開會日程中的特定筆記或參考檔案。"""
    orch = await get_orch()
    meeting = await orch.db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    target_file = next((f for f in meeting.attachments if f.id == file_id), None)
    if not target_file:
        if meeting.notes_file_path:
            p = Path(meeting.notes_file_path)
            if p.exists():
                media_type = "application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream"
                return FileResponse(path=str(p), media_type=media_type, filename=meeting.notes_filename or p.name)
        raise HTTPException(status_code=404, detail="File attachment not found")

    p = Path(target_file.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_type = "application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream"
    return FileResponse(path=str(p), media_type=media_type, filename=target_file.filename or p.name)


@app.delete("/api/meetings/{meeting_id}/files/{file_id}")
async def delete_meeting_file(meeting_id: str, file_id: str):
    """從開會日程中移除指定筆記檔案。"""
    orch = await get_orch()
    meeting = await orch.db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    target_file = next((f for f in meeting.attachments if f.id == file_id), None)
    if target_file:
        try:
            p = Path(target_file.file_path)
            if p.exists():
                p.unlink()
        except Exception:
            pass
        meeting.attachments = [f for f in meeting.attachments if f.id != file_id]
        if meeting.notes_file_path == target_file.file_path:
            meeting.notes_file_path = meeting.attachments[0].file_path if meeting.attachments else ""
            meeting.notes_filename = meeting.attachments[0].filename if meeting.attachments else ""
        await orch.db.upsert_meeting(meeting)

    return {"status": "success"}


@app.get("/api/meetings/{meeting_id}/notes-file")
async def download_meeting_notes_file(meeting_id: str):
    """下載或瀏覽開會日程關聯的筆記或簡報文件（預設第一份）。"""
    orch = await get_orch()
    meeting = await orch.db.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    path_to_use = ""
    name_to_use = ""
    if meeting.attachments:
        path_to_use = meeting.attachments[0].file_path
        name_to_use = meeting.attachments[0].filename
    elif meeting.notes_file_path:
        path_to_use = meeting.notes_file_path
        name_to_use = meeting.notes_filename

    if not path_to_use or not Path(path_to_use).exists():
        raise HTTPException(status_code=404, detail="Notes file not found on disk")

    p = Path(path_to_use)
    media_type = "application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream"
    return FileResponse(path=str(p), media_type=media_type, filename=name_to_use or p.name)


@app.delete("/api/meetings/{meeting_id}")
async def delete_meeting(meeting_id: str):
    orch = await get_orch()
    meeting = await orch.db.get_meeting(meeting_id)
    if meeting:
        for att in meeting.attachments:
            try:
                p = Path(att.file_path)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        if meeting.notes_file_path:
            try:
                p = Path(meeting.notes_file_path)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
    await orch.db.delete_meeting(meeting_id)
    return {"status": "success"}


# ==================== 課程與作業 (COURSES & ASSIGNMENTS) ====================

@app.delete("/api/courses/{course_id}")
async def delete_course(course_id: str):
    """刪除指定課程及其所有作業、子任務與向量索引。"""
    orch = await get_orch()
    await orch.db.delete_course(course_id)
    orch.vectors.delete_course(course_id)
    return {"status": "success", "message": f"Course {course_id} deleted"}


@app.post("/api/assignments")
async def create_assignment(
    course_id: str = Form(...),
    title: str = Form(...),
    due_date: str = Form(...),
    weight: float = Form(0.1),
    assignment_type: str = Form("other"),
    description: str = Form(""),
):
    """手動或手機端新增作業項目"""
    orch = await get_orch()
    courses = await orch.db.list_courses()
    
    target_course_id = course_id
    if not any(c.id == course_id for c in courses):
        if courses:
            target_course_id = courses[0].id
        else:
            raise HTTPException(status_code=400, detail="尚無任何課程，請先匯入課綱或建立課程")

    clean_date = due_date.strip().replace(" ", "T")
    if len(clean_date) == 10:
        clean_date += "T23:59:00"
    elif len(clean_date) == 16:
        clean_date += ":00"

    try:
        dt = datetime.fromisoformat(clean_date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    assign_id = f"{target_course_id}-A{uuid.uuid4().hex[:6].upper()}"
    new_assignment = Assignment(
        id=assign_id,
        course_id=target_course_id,
        title=title,
        description=description,
        assignment_type=AssignmentType(assignment_type) if assignment_type in [t.value for t in AssignmentType] else AssignmentType.OTHER,
        due_date=dt,
        weight=weight,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    await orch.db.upsert_assignment(new_assignment)
    return {"status": "success", "assignment_id": assign_id, "message": "Assignment created successfully", "title": title}


@app.post("/api/assignments/{assignment_id}/due-date")
async def update_assignment_due_date(
    assignment_id: str,
    due_date: str = Form(...),
):
    """手動更新指定作業的截止日期與時間。"""
    orch = await get_orch()
    # 格式化日期時間
    clean_date = due_date.strip().replace(" ", "T")
    if len(clean_date) == 10:
        clean_date += "T12:00:00"
    elif len(clean_date) == 16:
        clean_date += ":00"

    try:
        dt = datetime.fromisoformat(clean_date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")

    await orch.db.update_assignment_due_date(assignment_id, dt.isoformat())
    return {"status": "success", "assignment_id": assignment_id, "due_date": dt.isoformat()}


@app.delete("/api/assignments/{assignment_id}")
async def delete_assignment(assignment_id: str):
    """刪除指定作業項目。"""
    orch = await get_orch()
    await orch.db.delete_assignment(assignment_id)
    return {"status": "success", "message": f"Assignment {assignment_id} deleted"}


@app.get("/api/courses/{course_id}/resources")
async def get_course_resources(course_id: str):
    """取得指定課程的所有延伸資料。"""
    orch = await get_orch()
    res = await orch.db.list_course_resources(course_id)
    return {"status": "success", "resources": res}


@app.post("/api/courses/{course_id}/resources")
async def add_course_resource(
    course_id: str,
    title: str = Form(...),
    resource_type: str = Form("paper"),
    url_or_ref: str = Form(""),
    summary: str = Form(""),
    relevance: str = Form(""),
):
    orch = await get_orch()
    res_obj = {
        "id": f"res-{uuid.uuid4().hex[:8]}",
        "course_id": course_id,
        "title": title,
        "resource_type": resource_type,
        "url_or_ref": url_or_ref,
        "summary": summary,
        "relevance": relevance,
        "added_by": "user",
        "created_at": datetime.now().isoformat(),
    }
    await orch.db.add_course_resource(res_obj)
    return {"status": "success", "resource": res_obj}


@app.post("/api/courses/{course_id}/generate-resources")
async def generate_course_resources(course_id: str):
    orch = await get_orch()
    course = await orch.db.get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    assignments = await orch.db.get_assignments_by_course(course_id)
    assignment_titles = ", ".join(a.title for a in assignments) if assignments else "綜合期末評量"

    prompt = f"""請為以下大學/研究所專業課程，推薦 3-4 篇真實存在的權威學術文獻、經典著作或知名案例研究 (Extended Academic Literature & Case Studies)：

課程代碼：{course.id}
課程名稱：{course.name}
授課教授：{course.professor or '未提供'}
核心理論框架：{', '.join(course.theory_frameworks) or '專業核心學科理論'}
本課程評量作業：{assignment_titles}

嚴格要求：
1. 必須是真實存在、可於 Google Scholar / Scopus 檢索到的文獻，作者姓名、年份與著作標題必須完全真實。
2. 針對該課程之特定核心理論（例如：Gibbs reflective cycle, Kolb learning cycle, Porter's models, Dunning OLI 等）提供權威原始文獻與最新實證研究。

請輸出 JSON 陣列（置於 ```json ... ``` 區塊內），每個項目包含：
- "title": 文獻或著作名稱 (包含作者與發表年份，例如：Gibbs, G. (1988) Learning by Doing: A guide to teaching and learning methods)
- "resource_type": "paper" (學術論文) | "book" (權威書籍) | "case_study" (經典案例)
- "url_or_ref": 建議檢索關鍵字、DOI 或經典期刊出處
- "summary": 2-3 句中文精華摘要，解釋該文獻核心觀點
- "relevance": 說明此延伸資料如何幫助學生在 {course.id} 這門課或特定作業中拿到更高分數
"""
    try:
        try:
            raw_res = await orch.llm.generate_grounded(prompt=prompt, temperature=0.3)
            items = extract_json(raw_res)
        except Exception:
            raw_res = await orch.llm.generate_json(prompt=prompt, temperature=0.3)
            items = extract_json(raw_res)

        if isinstance(items, dict):
            items = items.get("resources", items.get("items", []))
        
        saved = []
        for it in items:
            if not isinstance(it, dict):
                continue
            res_obj = {
                "id": f"res-{uuid.uuid4().hex[:8]}",
                "course_id": course_id,
                "title": it.get("title", "延伸文獻"),
                "resource_type": it.get("resource_type", "paper"),
                "url_or_ref": it.get("url_or_ref", ""),
                "summary": it.get("summary", ""),
                "relevance": it.get("relevance", ""),
                "added_by": "ai",
                "created_at": datetime.now().isoformat(),
            }
            await orch.db.add_course_resource(res_obj)
            saved.append(res_obj)

        return {"status": "success", "generated": saved}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/courses/{course_id}/upload-resource-pdf")
async def upload_course_resource_pdf(
    course_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
    summary: str = Form(""),
    relevance: str = Form(""),
):
    """上傳課程延伸論文、講義或參考教材 PDF，並自動萃取文字加入向量知識庫。"""
    orch = await get_orch()
    course_dir = RESOURCE_DIR / course_id
    course_dir.mkdir(parents=True, exist_ok=True)

    dest_path = course_dir / file.filename
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 1. 抽取 PDF 內文
    from pypdf import PdfReader
    extracted_text = ""
    try:
        reader = PdfReader(str(dest_path))
        extracted_text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:
        extracted_text = ""

    # 2. 將 PDF 內容分塊加入 ChromaDB 向量知識庫！
    if extracted_text.strip():
        parser = orch.sub_agents.get("context_parser")
        if parser:
            chunks = parser._chunk_text(extracted_text, course_id, str(dest_path))
            orch.vectors.add_chunks(course_id, chunks)

    # 3. 若無摘要，讓 AI 自動產生簡短兩句核心摘要
    clean_summary = summary.strip()
    if not clean_summary and extracted_text.strip():
        try:
            brief_p = f"請用 2 句話中文總結這份學術文獻或教材的核心觀點與對課程的幫助：\n\n{extracted_text[:3000]}"
            clean_summary = await orch.llm.generate(prompt=brief_p, temperature=0.3)
            clean_summary = clean_summary.strip()[:300]
        except Exception:
            clean_summary = f"學生上傳之延伸參考資料《{file.filename}》"

    res_id = f"res-{uuid.uuid4().hex[:8]}"
    item_title = title.strip() or file.filename
    res_obj = {
        "id": res_id,
        "course_id": course_id,
        "title": item_title,
        "resource_type": "pdf",
        "url_or_ref": f"/api/resources/{res_id}/file",
        "summary": clean_summary or f"已成功解析並索引《{file.filename}》至課程向量知識庫",
        "relevance": relevance.strip() or "已建立向量嵌入，可在開工彈藥包與開會備料中即時引用",
        "added_by": "user",
        "file_path": str(dest_path.resolve()),
        "created_at": datetime.now().isoformat(),
    }

    await orch.db.add_course_resource(res_obj)
    return {"status": "success", "resource": res_obj}


@app.get("/api/resources/{resource_id}/file")
async def get_resource_file(resource_id: str):
    """下載或線上瀏覽已上傳之課程延伸 PDF。"""
    orch = await get_orch()
    res = await orch.db.get_course_resource(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")

    file_path = res.get("file_path")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=Path(file_path).name,
    )


@app.delete("/api/resources/{resource_id}")
async def delete_resource(resource_id: str):
    orch = await get_orch()
    res = await orch.db.get_course_resource(resource_id)
    if res and res.get("file_path"):
        try:
            fp = Path(res["file_path"])
            if fp.exists():
                fp.unlink()
        except Exception:
            pass
    await orch.db.delete_course_resource(resource_id)
    return {"status": "success"}


# ==================== 行事曆同步 (.ICS) ====================

@app.get("/api/calendar.ics")
async def download_calendar_ics():
    """動態生成標準 iCalendar (.ics) 檔案，包含截止日、建議動工日、開會日程與每週上課課表！"""
    orch = await get_orch()
    courses = await orch.db.list_courses()
    meetings = await orch.db.list_meetings()
    timetable = await orch.db.list_timetable_slots()
    
    now_str = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Academic Chief of Staff//Academic Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:智慧學業幕僚 — 課業、動工與上課課表",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]

    for c in courses:
        assignments = await orch.db.get_assignments_by_course(c.id)
        for a in assignments:
            if not a.due_date:
                continue
            due_str = a.due_date.strftime("%Y%m%dT%H%M%S")
            plan = orch.calculate_backward_plan(a)
            kickoff_date = plan[0]["target_date"] if plan else ""

            # 1. 截止日
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:deadline-{a.id}@chief-of-staff",
                f"DTSTAMP:{now_str}",
                f"DTSTART:{due_str}",
                f"DTEND:{due_str}",
                f"SUMMARY:🔴 [截止繳交] {c.id}: {a.title} ({int(a.weight*100)}%)",
                f"DESCRIPTION:課程：{c.name}\\n教授：{c.professor}\\n佔分比重：{int(a.weight*100)}%\\n建議最晚動工日：{kickoff_date}\\n字數限制：{a.word_limit or '未指定'}",
                "BEGIN:VALARM",
                "TRIGGER:-P1D",
                "ACTION:DISPLAY",
                f"DESCRIPTION:【明天截止提醒】{a.title} 倒數 24 小時！",
                "END:VALARM",
                "BEGIN:VALARM",
                "TRIGGER:-PT3H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:【即將截止緊急提醒】{a.title} 倒數 3 小時！",
                "END:VALARM",
                "END:VEVENT",
            ])

            # 2. 建議動工日
            if plan and len(plan) > 0:
                kickoff_target = datetime.fromisoformat(plan[0]["target_date"]).strftime("%Y%m%dT090000")
                lines.extend([
                    "BEGIN:VEVENT",
                    f"UID:kickoff-{a.id}@chief-of-staff",
                    f"DTSTAMP:{now_str}",
                    f"DTSTART:{kickoff_target}",
                    f"DTEND:{kickoff_target}",
                    f"SUMMARY:🚀 [建議動工] {c.id}: {a.title} (倒數 {plan[0]['days_before']} 天)",
                    f"DESCRIPTION:依據作業比重 ({int(a.weight*100)}%) 與難度，智慧幕僚建議您今天開始動工！\\n階段目標：{plan[0]['desc']}",
                    "BEGIN:VALARM",
                    "TRIGGER:PT0M",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:【動工提醒】{c.id}: {a.title} 建議今天開始動工！",
                    "END:VALARM",
                    "END:VEVENT",
                ])

    # 3. 開會日程
    for m in meetings:
        m_start = m.meeting_time.strftime("%Y%m%dT%H%M%S")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{m.id}@chief-of-staff",
            f"DTSTAMP:{now_str}",
            f"DTSTART:{m_start}",
            f"DTEND:{m_start}",
            f"SUMMARY:🤝 [討論開會] {m.course_id}: {m.title}",
            f"LOCATION:{m.location}",
            f"DESCRIPTION:開會主題：{m.topic_description}\\nAI 備妥資料請至幕僚儀表板查閱。",
            "BEGIN:VALARM",
            "TRIGGER:-PT30M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:【開會提醒】{m.title} 30 分鐘後開始！",
            "END:VALARM",
            "END:VEVENT",
        ])

    # 4. 每週課表 (週循環日程)
    day_map = {1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA", 7: "SU"}
    today = date.today()
    for s in timetable:
        day_diff = (s["day_of_week"] - today.isoweekday()) % 7
        target_day = today + timedelta(days=day_diff)
        st_clean = s["start_time"].replace(":", "") + "00"
        et_clean = s["end_time"].replace(":", "") + "00"
        st_full = target_day.strftime("%Y%m%d") + "T" + st_clean
        et_full = target_day.strftime("%Y%m%d") + "T" + et_clean
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{s['id']}@chief-of-staff-timetable",
            f"DTSTAMP:{now_str}",
            f"DTSTART:{st_full}",
            f"DTEND:{et_full}",
            f"RRULE:FREQ=WEEKLY;BYDAY={day_map.get(s['day_of_week'], 'MO')};UNTIL=20270131T235959Z",
            f"SUMMARY:📖 [課程] {s['course_id']}: {s.get('course_name') or s['course_id']} ({s.get('class_type', 'Lecture')})",
            f"LOCATION:{s.get('classroom', '')} - {s.get('location', '')}",
            f"DESCRIPTION:授課教師：{s.get('professor', '')}\\n教室：{s.get('classroom', '')}\\n地點：{s.get('location', '')}",
            "BEGIN:VALARM",
            "TRIGGER:-PT15M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:【上課提醒】{s['course_id']} 15 分鐘後在 {s.get('classroom', '')} 上課！",
            "END:VALARM",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    ics_content = "\r\n".join(lines)

    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="academic_schedule.ics"'}
    )


@app.post("/api/notify-desktop")
async def notify_desktop(title: str = Form(...), message: str = Form(...)):
    """發送 macOS 原生桌面推播通知"""
    notifier = await get_notifier()
    await notifier.send(title=title, message=message, priority=3)
    return {"status": "success"}


# ==================== 課綱上傳 (UPLOAD) ====================

@app.post("/api/upload")
async def upload_syllabi(files: List[UploadFile] = File(...)):
    orch = await get_orch()
    results = []

    for f in files:
        temp_path = UPLOAD_DIR / f.filename
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(f.file, buffer)

        try:
            res = await orch.execute({
                "action": "ingest_syllabus",
                "file_path": str(temp_path.resolve()),
            })
            if res.get("status") == "success":
                course = res.get("course")
                results.append({
                    "filename": f.filename,
                    "status": "success",
                    "course_id": course.id,
                    "course_name": course.name,
                    "assignments_count": len(course.assignments),
                })
            else:
                results.append({
                    "filename": f.filename,
                    "status": res.get("status", "error"),
                    "message": res.get("message", "解析失敗"),
                })
        except Exception as e:
            results.append({
                "filename": f.filename,
                "status": "error",
                "message": str(e),
            })

    return {"status": "success", "results": results}


@app.post("/api/starter-pack")
async def generate_starter_pack(assignment_id: str = Form(...), course_id: str = Form(...)):
    orch = await get_orch()
    researcher = orch.sub_agents.get("deep_researcher")
    synthesizer = orch.sub_agents.get("synthesizer")

    if not researcher or not synthesizer:
        raise HTTPException(status_code=500, detail="Agents not initialized")

    r_res = await researcher.execute({
        "action": "research_for_assignment",
        "assignment_id": assignment_id,
        "course_id": course_id,
    })

    if r_res.get("status") != "success":
        raise HTTPException(status_code=500, detail=r_res.get("message", "文獻檢索失敗"))

    s_res = await synthesizer.execute({
        "action": "generate_starter_pack",
        "assignment_id": assignment_id,
        "research_notes": r_res.get("notes", []),
    })

    if s_res.get("status") != "success":
        raise HTTPException(status_code=500, detail=s_res.get("message", "生成彈藥包失敗"))

    return s_res


@app.post("/api/rubric-check")
async def rubric_check(assignment_id: str = Form(...), draft: str = Form(...)):
    orch = await get_orch()
    synthesizer = orch.sub_agents.get("synthesizer")

    if not synthesizer:
        raise HTTPException(status_code=500, detail="Synthesizer agent not initialized")

    res = await synthesizer.execute({
        "action": "rubric_check",
        "assignment_id": assignment_id,
        "draft": draft,
    })

    return res
