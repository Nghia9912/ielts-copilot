from __future__ import annotations

import os
from pathlib import Path

# Xác định thư mục gốc của dự án (F:\ielts-copilot)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("IELTS_DB_PATH", str(DATA_DIR / "ielts_copilot.db")))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "qwen3:8b")
BASELINE_MODEL = os.getenv("OLLAMA_BASELINE_MODEL", "gemma3:4b")
BACKEND_HOST = "127.0.0.1"  # Luôn chỉ bind vào localhost để bảo mật dữ liệu học viên
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
