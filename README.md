# 🎓 Academic Chief of Staff (智慧學業幕僚多代理系統)

> **An autonomous multi-agent academic companion & executive cockpit for university students.**  
> Powered by Google Gemini, Microsoft Graph API, and FastAPI.

---

## 🌟 Overview (專案簡介)

**Academic Chief of Staff** is an intelligent, autonomous multi-agent operating system designed to eliminate academic anxiety and cognitive overload for university students. 

Instead of juggling fragmented LMS portals, syllabi PDFs, calendar conflicts, and tight submission deadlines, this system serves as your personal academic executive assistant:
- Automatically digests course syllabi and rubrics.
- Predicts crunch weeks and models grade targets.
- Prepares literature review starter packs and meeting pre-briefs.
- Keeps you focused with integrated anti-procrastination sprints and live mobile push notifications.

---

## ✨ Key Features (核心亮點)

### 1. 📄 Context-Aware Syllabus & Brief Ingestion
- Batch-parses PDF and DOCX syllabi using Google Gemini to extract course frameworks, weighted deliverables, backward milestone kickoff dates, and full grading rubrics.
- Automatically vectorizes materials into ChromaDB for context-anchored academic citation.

### 2. 📊 What-If Grade & GPA Target Solver
- Interactive score simulator modeled on UK Honours classification (First Class 70%+, 2:1, 2:2) and Glasgow 22-point scale.
- **Target Solver**: Backward-calculates exact average scores required on remaining assignments to secure a First Class degree.

### 3. ⏱️ Anti-Procrastination Pomodoro Sprint
- Low-friction 25-minute deep work sprints embedded right in your top deliverable hero card.
- Plays gentle web audio chimes upon completion and automatically logs verified focus hours to SQLite.

### 4. 🔥 12-Week Semester Workload Heatmap
- Visualizes weekly grading pressure across Weeks 1 to 12.
- Flags dangerous overlapping deadline clusters ("Crunch Weeks") with automated war-room action plans.

### 5. 👥 Deliverables Categorization
- Automatically categorizes assignments into **Individual Work (👤)** and **Group Projects (👥)** with one-click filtering.

### 6. 📱 Real-Time Mobile Companion & Push Alerts
- Zero-friction mobile web app with QR code pairing.
- Allows students to log assignments on the go, snap photos of whiteboard meeting notes, and receive lock-screen alerts prior to deadlines.

### 7. 🔍 Rubric Critic (Strict TA Red-Team Review)
- Audits draft essays and presentations against official rubric criteria before actual submission to expose scoring landmines and format gaps.

---

## 🛠️ Architecture & Tech Stack

```text
                           ┌─────────────────────────┐
                           │   Chief Orchestrator    │
                           │       (Agent 0)         │
                           └────────────┬────────────┘
        ┌───────────────────┬───────────┴───────────┬───────────────────┐
        ▼                   ▼                       ▼                   ▼
 Context Parser      Outlook Engine          Deep Researcher     Synthesizer & Critic
   (Agent 1)           (Agent 2)               (Agent 3)              (Agent 4)
        └───────────────────┴───────────┬───────────┴───────────────────┘
                                        ▼
                             SQLite Store + ChromaDB
                                        ▼
                       FastAPI + Responsive Web Dashboard
```

- **Backend**: Python 3.11+, FastAPI, Uvicorn, SQLite (aiosqlite), ChromaDB, Pydantic v2
- **AI / LLM**: Google Gemini API (`google-genai`)
- **Integrations**: Microsoft Graph API (Outlook Calendar & Delta Inbox Monitor), Ntfy.sh (WebPush)
- **Frontend**: Tailwind CSS, Lucide Icons, Mobile-Optimized Responsive Web UI

---

## 🚀 Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/<your-username>/academic-chief-of-staff.git
cd academic-chief-of-staff
```

### 2. Create environment & install dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Setup configuration
```bash
cp .env.example .env
# Edit .env and supply your GEMINI_API_KEY
```

### 4. Launch the Web Cockpit
```bash
python run_web.py
```
Open **`http://127.0.0.1:8400`** in your browser.

---

## 📄 License
MIT License. Built for students striving for academic excellence and balanced well-being.
