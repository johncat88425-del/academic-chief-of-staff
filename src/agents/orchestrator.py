"""Agent 0: Chief Orchestrator — 全局狀態管理、衝突協調、晨間簡報。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agents.base import BaseAgent
from src.models import Assignment, ConflictAlert, AlertSeverity
from src.utils.prompts import ORCHESTRATOR_PROMPT

console = Console()


class OrchestratorAgent(BaseAgent):
    """Chief Orchestrator: coordinates all agents and manages global state."""

    def __init__(self, **kwargs):
        super().__init__(name="orchestrator", **kwargs)
        self.sub_agents: dict[str, BaseAgent] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        """Register a sub-agent for orchestration."""
        self.sub_agents[agent.name] = agent
        self.logger.info(f"Registered sub-agent: {agent.name}")

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Route tasks to appropriate sub-agents or handle directly."""
        action = task.get("action", "")
        
        handlers = {
            "morning_brief": self._morning_brief,
            "conflict_check": self._conflict_check,
            "ingest_syllabus": self._ingest_syllabus,
            "starter_pack_check": self._starter_pack_check,
            "prepare_meeting_brief": self._prepare_meeting_brief,
            "full_scan": self._full_scan,
        }

        handler = handlers.get(action)
        if handler:
            return await handler(task)
        
        return {"status": "error", "message": f"Unknown action: {action}"}

    async def _morning_brief(self, task: dict[str, Any]) -> dict[str, Any]:
        """Generate the daily morning briefing with inbox and deadline updates."""
        upcoming = await self.db.get_upcoming_assignments(within_days=21)
        
        # 1. 學校信箱動態掃描 (Inbox Monitor)
        outlook = self.sub_agents.get("outlook_engine")
        inbox_updates = []
        if outlook:
            courses = await self.db.list_courses()
            res = await outlook.execute({"action": "scan_inbox", "course_codes": [c.id for c in courses]})
            inbox_updates = res.get("new_messages", [])

        # 2. 顯示信箱摘要
        if inbox_updates:
            mail_lines = "\n".join(f"• [{m.get('from', '學校')}] {m.get('subject', '課程通知')} ({m.get('received', '')[:10]})" for m in inbox_updates[:3])
            console.print(Panel(
                f"📬 學校信箱最新重要通知 ({len(inbox_updates)} 則)：\n{mail_lines}",
                title="📬 信箱雷達速報",
                border_style="magenta",
            ))

        if not upcoming:
            console.print(Panel("☀️ 未來 21 天內無即將到期的作業。祝今天學習愉快！",
                               title="Morning Briefing", border_style="green"))
            return {
                "status": "success",
                "assignments": [],
                "inbox_updates": inbox_updates,
                "conflicts": 0,
            }

        table = Table(title="📋 即將到期作業 (未來 21 天)")
        table.add_column("課程代碼", style="cyan")
        table.add_column("作業名稱", style="white")
        table.add_column("截止日期", style="yellow")
        table.add_column("佔分比重", justify="right", style="magenta")
        table.add_column("建議動工日", style="green")
        table.add_column("剩餘天數", justify="right")

        now = datetime.now()
        backward_plans = {}
        for a in upcoming:
            plan = self.calculate_backward_plan(a)
            backward_plans[a.id] = plan
            kickoff_date = plan[0]["target_date"] if plan else "儘速動工"
            days_left = (a.due_date - now).days if a.due_date else 0
            urgency_style = "red bold" if days_left <= 3 else "yellow" if days_left <= 7 else "green"
            table.add_row(
                a.course_id, a.title,
                a.due_date.strftime("%Y-%m-%d") if a.due_date else "未定",
                f"{a.weight*100:.0f}%",
                f"{kickoff_date}",
                f"[{urgency_style}]{days_left}d[/]",
            )

        console.print(Panel.fit(table, title="☀️ 晨間簡報 — 截止日與逆向規劃", border_style="blue"))
        
        conflicts = await self._detect_conflicts(upcoming)
        for alert in conflicts:
            severity_style = "red" if alert.severity == AlertSeverity.CRITICAL else "yellow"
            console.print(Panel(
                f"{alert.message}\n\n💡 建議：{alert.resolution_proposed}",
                title=f"⚠️ {alert.severity.value.upper()} 衝突預警",
                border_style=severity_style,
            ))

        return {
            "status": "success",
            "assignments": [a.id for a in upcoming],
            "inbox_updates": inbox_updates,
            "backward_plans": backward_plans,
            "conflicts": len(conflicts),
        }

    def calculate_backward_plan(self, assignment: Assignment) -> list[dict]:
        """根據作業佔分比重與難度，自動計算逆向排程動工日與各階段目標。"""
        from datetime import timedelta
        due = assignment.due_date or (datetime.now() + timedelta(days=30))
        weight = assignment.weight

        if weight >= 0.30:
            lead_days = 21
            milestones = [
                {"phase": "🚀 階段一：動工破題與框架鎖定 (Kickoff)", "days_before": 21, "desc": "確立核心論點、界定分析範圍與課堂理論框架"},
                {"phase": "📚 階段二：深度文獻檢索與案例收集", "days_before": 14, "desc": "檢索 3-5 篇緊扣主題的學術文獻與實務案例"},
                {"phase": "✍️ 階段三：章節大綱與初稿撰寫", "days_before": 7, "desc": "完成符合字數限制的第一版完整草稿"},
                {"phase": "🔍 階段四：嚴格助教紅隊審查與格式潤飾", "days_before": 3, "desc": "逐條比對 Rubric 評分項目、檢查引用格式 (APA/Harvard)"},
                {"phase": "🏁 階段五：最終審查與繳交截止", "days_before": 0, "desc": "最後檢查繳交檔案格式，準時上傳 Moodle/Canvas"},
            ]
        elif weight >= 0.20:
            lead_days = 14
            milestones = [
                {"phase": "🚀 階段一：動工破題與文獻大綱 (Kickoff)", "days_before": 14, "desc": "理解作業要求，擬定整體大綱結構"},
                {"phase": "✍️ 階段二：撰寫核心分析初稿", "days_before": 6, "desc": "套用課堂分析模型，完成主體內容"},
                {"phase": "🔍 階段三：評分標準對齊與潤飾", "days_before": 2, "desc": "比對 Rubric 評分標準，修正缺漏處"},
                {"phase": "🏁 階段四：最終繳交截止", "days_before": 0, "desc": "檢查檔案命名與格式後上傳"},
            ]
        elif weight >= 0.10:
            lead_days = 7
            milestones = [
                {"phase": "🚀 階段一：動工準備與架構 (Kickoff)", "days_before": 7, "desc": "研讀作業說明，列出所需答題要點"},
                {"phase": "✍️ 階段二：撰寫與解答", "days_before": 3, "desc": "完成主要論述或計算作業"},
                {"phase": "🏁 階段三：核對與繳交", "days_before": 0, "desc": "檢查完整度並繳交"},
            ]
        else:
            lead_days = 4
            milestones = [
                {"phase": "🚀 階段一：動工撰寫 (Kickoff)", "days_before": 4, "desc": "開始準備作業內容"},
                {"phase": "🏁 階段二：最終繳交", "days_before": 0, "desc": "檢查後送出"},
            ]

        results = []
        for m in milestones:
            target_dt = due - timedelta(days=m["days_before"])
            results.append({
                "phase": m["phase"],
                "target_date": target_dt.strftime("%Y-%m-%d"),
                "days_before": m["days_before"],
                "desc": m["desc"],
                "is_kickoff": m["days_before"] == lead_days,
            })
        return results

    async def _prepare_meeting_brief(self, task: dict[str, Any]) -> dict[str, Any]:
        """為即將到來的會議或討論，自動聯網檢索理論並生成專屬開會備料包。"""
        course_id = task.get("course_id", "")
        assignment_id = task.get("assignment_id", "")
        topic = task.get("topic", "")
        meeting_time = task.get("meeting_time", "")

        course = await self.db.get_course(course_id)
        assignment = None
        if assignment_id and course:
            assignments = await self.db.get_assignments_by_course(course_id)
            assignment = next((a for a in assignments if a.id == assignment_id), None)

        frameworks_str = ", ".join(course.theory_frameworks) if (course and course.theory_frameworks) else "該專業領域核心學術理論"
        prof_name = course.professor if course else "授課教授"
        
        # 檢索向量資料庫中與該主題相關的課程片段
        query_text = f"{topic} {assignment.title if assignment else ''}"
        try:
            chunks = self.vectors.query(course_id=course_id, query_text=query_text, n_results=3)
            context_text = "\n---\n".join(c["content"] for c in chunks)
        except Exception:
            context_text = ""

        assignment_details = ""
        if assignment:
            assignment_details = f"""
作業名稱：{assignment.title}
佔分比重：{assignment.weight*100:.0f}%
作業要求：{assignment.description[:800]}
評分標準：{', '.join(r.criterion for r in assignment.rubric[:4]) if assignment.rubric else '依一般學術標準'}
"""

        prompt = f"""請為以下大學/研究所學術會議，準備一份極具深度與專業度的小組/教授開會資料備料包 (Pre-Meeting Research Brief)：

課程名稱與代碼：{course.name if course else ''} ({course_id})
授課教授：{prof_name}
核心理論框架：{frameworks_str}
針對作業：{assignment_details or assignment_id or '學期專案/課堂討論'}
開會主題與探討問題：{topic}
預定開會時間：{meeting_time}

課程相關參考脈絡：
{context_text}

請產生一份完整的 Markdown 開會手冊，包含：
1. 【🎯 會議核心目標與 3 項預期決策成果】
2. 【🧠 必須套用的課堂理論框架與分析切入點】（緊扣上述課程理論框架，詳細說明如何具體套用）
3. 【🔍 小組爭執點與深度探討問題 (Discussion Questions)】（列出 3-4 個最具批判性思維的討論點）
4. 【📚 建議引用的外部真實權威文獻/實務案例與數據】（列出 2-3 個真實存在的經典著作或近 5 年權威期刊論文，務必真實準確）
5. 【📋 會後行動分配建議清單 (Action Items)】

拒絕空泛的通用廢話，內容必須高度具體，契合該門課程之專業水準。
"""
        try:
            brief_content = await self.llm.generate_grounded(
                prompt=prompt,
                system_instruction="你是一位頂級學術首席幕僚與 MBA 專案教練，擅長為高強度學術會議提供最精準的議程與真實文獻準備。",
                temperature=0.3,
            )
        except Exception:
            brief_content = await self.llm.generate(
                prompt=prompt,
                system_instruction="你是一位頂級學術首席幕僚與 MBA 專案教練，擅長為高強度學術會議提供最精準的議程與真實文獻準備。",
                temperature=0.3,
            )

        return {
            "status": "success",
            "brief_content": brief_content,
        }

    async def _conflict_check(self, task: dict[str, Any]) -> dict[str, Any]:
        """Check for scheduling conflicts across all upcoming assignments."""
        upcoming = await self.db.get_upcoming_assignments(within_days=30)
        conflicts = await self._detect_conflicts(upcoming)
        return {"status": "success", "conflicts": [c.model_dump() for c in conflicts]}

    async def _detect_conflicts(self, assignments: list[Assignment]) -> list[ConflictAlert]:
        """Detect weeks where high-weight assignments overlap."""
        from src.config import settings as app_settings
        
        alerts: list[ConflictAlert] = []
        if not assignments:
            return alerts

        weekly: dict[str, list[Assignment]] = {}
        for a in assignments:
            week_key = a.due_date.strftime("%Y-W%W")
            weekly.setdefault(week_key, []).append(a)

        for week_key, week_assignments in weekly.items():
            if len(week_assignments) < 2:
                continue
            total_weight = sum(a.weight for a in week_assignments)
            if total_weight >= app_settings.crunch_week_threshold:
                alert = ConflictAlert(
                    id=f"conflict-{week_key}",
                    severity=AlertSeverity.CRITICAL if total_weight >= 0.5 else AlertSeverity.WARNING,
                    week_start=min(a.due_date for a in week_assignments),
                    conflicting_assignment_ids=[a.id for a in week_assignments],
                    total_weight=total_weight,
                    message=(
                        f"Crunch Week Alert: {len(week_assignments)} assignments "
                        f"totaling {total_weight*100:.0f}% of grades due in week {week_key}"
                    ),
                    resolution_proposed=(
                        f"Consider starting the heaviest assignment "
                        f"({max(week_assignments, key=lambda a: a.weight).title}) "
                        f"one week earlier."
                    ),
                )
                alerts.append(alert)

        return alerts

    async def _ingest_syllabus(self, task: dict[str, Any]) -> dict[str, Any]:
        """Delegate syllabus parsing to Agent 1 (Context Parser)."""
        parser = self.sub_agents.get("context_parser")
        if not parser:
            return {"status": "error", "message": "Context Parser agent not registered"}
        return await parser.execute(task)

    async def _starter_pack_check(self, task: dict[str, Any]) -> dict[str, Any]:
        """Check if any assignments need starter packs generated."""
        from src.config import settings as app_settings
        
        lead_days = app_settings.starter_pack_lead_days
        upcoming = await self.db.get_upcoming_assignments(within_days=lead_days + 3)
        
        needs_pack = [
            a for a in upcoming
            if not a.starter_pack_generated
            and (a.due_date - datetime.now()).days <= lead_days
        ]

        if not needs_pack:
            console.print("No starter packs needed right now.")
            return {"status": "success", "triggered": []}

        triggered = []
        for a in needs_pack:
            console.print(f"Triggering starter pack for: [bold]{a.title}[/] (due {a.due_date.strftime('%Y-%m-%d')})")
            researcher = self.sub_agents.get("deep_researcher")
            synthesizer = self.sub_agents.get("synthesizer")
            
            if researcher and synthesizer:
                research_result = await researcher.execute({
                    "action": "research_for_assignment",
                    "assignment_id": a.id,
                    "course_id": a.course_id,
                })
                if research_result.get("status") == "success":
                    await synthesizer.execute({
                        "action": "generate_starter_pack",
                        "assignment_id": a.id,
                        "research_notes": research_result.get("notes", []),
                    })
            triggered.append(a.id)

        return {"status": "success", "triggered": triggered}

    async def _full_scan(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run a full system scan: morning brief + conflict check + starter pack check."""
        brief = await self._morning_brief(task)
        packs = await self._starter_pack_check(task)
        return {
            "status": "success",
            "brief": brief,
            "starter_packs": packs,
        }
