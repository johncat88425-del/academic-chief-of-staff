"""Automated Background Reminder Engine.

Continuously monitors deadlines, kickoff dates, and scheduled meetings,
and proactively pushes notifications to the student's mobile phone and Mac desktop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from src.memory.sqlite_store import SQLiteStore
from src.services.notifier import MobileNotifier

logger = logging.getLogger(__name__)


class ReminderService:
    """Background engine that periodically evaluates deadlines and dispatches alerts."""

    def __init__(self, db: SQLiteStore, notifier: MobileNotifier):
        self.db = db
        self.notifier = notifier
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the background monitoring loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("ReminderService background monitor started.")

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        """Loop runs every 60 seconds."""
        # Initial wait to let server boot up completely
        await asyncio.sleep(5)
        while self._running:
            try:
                await self.check_and_notify()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ReminderService loop: {e}", exc_info=True)
            await asyncio.sleep(60)

    async def check_and_notify(self) -> dict:
        """Evaluate deadlines, kickoff dates, and meetings; dispatch push alerts."""
        now = datetime.now()
        today_str = date.today().isoformat()
        dispatched = []

        courses = await self.db.list_courses()

        # 1. Evaluate assignments for Kickoff & Deadlines
        for c in courses:
            assignments = await self.db.get_assignments_by_course(c.id)
            for a in assignments:
                if not a.due_date:
                    continue

                diff = a.due_date - now
                hours_left = diff.total_seconds() / 3600.0

                # A. 建議動工日提醒 (Kickoff Alert)
                # 依據比重推算動工天數：比重 >= 50% 為 14 天，>= 30% 為 10 天，其餘 7 天
                lead_days = 14 if a.weight >= 0.5 else (10 if a.weight >= 0.3 else 7)
                kickoff_target = (a.due_date - timedelta(days=lead_days)).date()

                if date.today() == kickoff_target:
                    event_key = f"kickoff-{a.id}-{today_str}"
                    if not await self.db.is_notification_sent(event_key):
                        title = f"🚀【建議動工提醒】{c.id}：{a.title}"
                        msg = (
                            f"此項作業佔分 {int(a.weight*100)}%，幕僚依據難度建議您今天開始動工（倒數 {lead_days} 天）！\n"
                            f"首階段目標：擬定大綱與核心文獻檢索。\n"
                            f"截止日期：{a.due_date.strftime('%m/%d %H:%M')}"
                        )
                        await self.notifier.send(
                            title=title,
                            message=msg,
                            priority=3,
                            tags=["rocket", "hourglass"],
                        )
                        await self.db.mark_notification_sent(event_key)
                        dispatched.append(event_key)

                # B. 截止日前 24 小時提醒 (T-24h Warning)
                if 0 < hours_left <= 24:
                    event_key = f"deadline-24h-{a.id}"
                    if not await self.db.is_notification_sent(event_key):
                        title = f"⏰【明天截止提醒】{c.id}：{a.title}"
                        msg = (
                            f"作業將在 24 小時以內截止！\n"
                            f"最後繳交時間：{a.due_date.strftime('%Y-%m-%d %H:%M')}\n"
                            f"佔分比重：{int(a.weight*100)}% | 限制：{a.word_limit or '未指定'}"
                        )
                        await self.notifier.send(
                            title=title,
                            message=msg,
                            priority=4,
                            tags=["warning", "alarm_clock"],
                        )
                        await self.db.mark_notification_sent(event_key)
                        dispatched.append(event_key)

                # C. 截止前 3 小時緊急提醒 (T-3h Urgent Alarm)
                if 0 < hours_left <= 3:
                    event_key = f"deadline-3h-{a.id}"
                    if not await self.db.is_notification_sent(event_key):
                        title = f"🚨【3小時緊急截止】{c.id}：{a.title}"
                        msg = (
                            f"作業已進入最後 3 小時緊急倒數！\n"
                            f"請立即確認繳交格式、參考文獻規範並提早上傳以避開伺服器塞車！"
                        )
                        await self.notifier.send(
                            title=title,
                            message=msg,
                            priority=5,
                            tags=["rotating_light", "fire"],
                        )
                        await self.db.mark_notification_sent(event_key)
                        dispatched.append(event_key)

        # 2. Evaluate meetings (30-minute pre-meeting alert)
        meetings = await self.db.list_meetings()
        for m in meetings:
            m_diff = m.meeting_time - now
            mins_left = m_diff.total_seconds() / 60.0
            if 0 < mins_left <= 30:
                event_key = f"meeting-30m-{m.id}"
                if not await self.db.is_notification_sent(event_key):
                    title = f"🤝【開會即將開始】{m.course_id}：{m.title}"
                    msg = (
                        f"預定開會時間：{m.meeting_time.strftime('%H:%M')}（約 {int(mins_left)} 分鐘後）\n"
                        f"地點：{m.location}\n"
                        f"主題：{m.topic_description or '專案討論'}\n"
                        f"AI 會議備料包已於幕僚儀表板備妥。"
                    )
                    await self.notifier.send(
                        title=title,
                        message=msg,
                        priority=4,
                        tags=["handshake", "calendar"],
                    )
                    await self.db.mark_notification_sent(event_key)
                    dispatched.append(event_key)

        # 3. 每日 08:00 AM 晨間簡報推播
        if now.hour == 8 and now.minute <= 5:
            event_key = f"morning-brief-{today_str}"
            if not await self.db.is_notification_sent(event_key):
                upcoming_count = 0
                for c in courses:
                    assignments = await self.db.get_assignments_by_course(c.id)
                    upcoming_count += sum(1 for a in assignments if a.due_date and 0 < (a.due_date - now).days <= 14)
                
                title = f"☀️【今日晨間學業簡報】{today_str}"
                msg = f"早安！目前未來 14 天內有 {upcoming_count} 項重要作業與評量即將來臨。請打開學業幕僚查看今日專注目標！"
                await self.notifier.send(
                    title=title,
                    message=msg,
                    priority=3,
                    tags=["sunny", "clipboard"],
                )
                await self.db.mark_notification_sent(event_key)
                dispatched.append(event_key)

        return {"status": "success", "dispatched_count": len(dispatched), "keys": dispatched}
