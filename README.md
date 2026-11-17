# IELTS Copilot — Offline Local Teaching Assistant

A 100% offline, privacy-preserving IELTS Teaching Assistant built for local execution on Windows using **FastAPI**, **SQLite**, **Ollama** (`qwen3:8b`, `gemma3:4b`), and **Faster-Whisper** (`small.en`).

## Core Modules

1. **Writing Lab (Task 1 & Task 2)**
   - **Task 1 Chart Vision**: Extracts structured reference figures and trends from chart/diagram images locally via `gemma3:4b`.
   - **Calibrated Assessment**: Evaluates essays on a 70% Strict Cambridge Examiner / 30% Constructive Leniency rubric (`ielts-writing-v2.2-balanced-70-30`) with zero cross-criterion double penalization and deterministic underlength ceilings.
   - **Verbatim Quote Verification**: Verifies AI-cited quotes 100% against the original submission with click-to-highlight inspection and detailed band-upgrading rewrite suggestions.
   - **Teacher Review**: Allows teachers to override final band scores and save official feedback.

2. **Speaking Lab (Offline Transcription & Assessment)**
   - Supports direct microphone recording, Zoom system audio capture, and audio file uploads (`.mp3`, `.wav`, `.m4a`, `.webm`, `.ogg`).
   - Transcribes speech offline via `faster-whisper` (`small.en`) and computes acoustic fluency metrics (WPM, speaking time, pause duration, long pause count).

3. **Student Records & Data Management**
   - Tracks student profiles, target bands, submission history, and recurring error tags (`ARTICLE`, `COLLOCATION`, `TR_UNDERDEVELOPED`, etc.) in SQLite.
   - Built-in one-click SQLite database backup/restore and cascading student/submission deletion with local audio file cleanup.

4. **Teaching Studio (7-Stage Guided Workflow)**
   - **Stages**: `1. Prepare Lesson` -> `2. Review Analysis` -> `3. Teaching Playbook` -> `4. Student Handout` -> `5. Teacher Guide & Key` -> `6. Teaching Companion` -> `7. Post-Lesson Review`.
   - **Local Material Library**: Ingests `.txt`, `.md`, `.docx`, and `.pdf` reference materials locally.
   - **Strict Separation**: Prevents answer-key leakage in student-facing handouts and separates teacher-confirmed notes from AI-generated hypotheses.
   - **Offline Document Export**: Generates multi-page `.docx` and `.pdf` files with full UTF-8 Vietnamese support.

## Project Structure

```text
ielts-copilot/
├── apps/
│   ├── backend/app/
│   │   ├── api/                # FastAPI routes (Core + Teaching Studio)
│   │   ├── core/               # Paths and runtime config
│   │   ├── db/                 # SQLite schema & Teaching Studio migrations
│   │   ├── prompts/            # Calibrated Writing & Teaching Studio prompts
│   │   ├── repositories/       # SQLite persistence layer
│   │   ├── schemas/            # Pydantic models
│   │   └── services/           # Ollama, Faster-Whisper, Writing, Studio Engine & Exporter
│   └── desktop/                # Single-page UI (Light/Dark theme) & Tauri config
├── tests/                      # Automated Teaching Studio test suite (12 suites)
├── Start_IELTS_Copilot.bat     # One-click Windows launcher
└── requirements.txt            # Python dependencies
```

## Setup & Usage (Windows)

### 1. Prerequisites
- **Python 3.11+**
- **[Ollama](https://ollama.com/)** installed with local models:

```powershell
ollama pull qwen3:8b
ollama pull gemma3:4b
```

### 2. Install Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
```

### 3. Run the Application
Double-click `Start_IELTS_Copilot.bat` or run manually from PowerShell:

```powershell
$env:PYTHONPATH = "apps\backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `[http://127.0.0.1:8000](http://127.0.0.1:8000)` in your browser.

### 4. Run Tests

```powershell
$env:PYTHONPATH = "apps\backend"
.\.venv\Scripts\python.exe tests\test_teaching_studio.py
```
