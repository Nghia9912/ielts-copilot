from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.api.studio_routes import studio_router
from app.db.database import init_db

UI_FILE = Path(__file__).resolve().parents[2] / "desktop" / "index.html"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="IELTS Copilot Local Backend",
    description="Local IELTS Teaching Assistant API (100% Offline - SQLite + Ollama)",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(studio_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_teacher_ui():
    if UI_FILE.exists():
        return UI_FILE.read_text(encoding="utf-8")
    return "<h1>IELTS Copilot UI not found. Run init_ui_mvp.py first.</h1>"
