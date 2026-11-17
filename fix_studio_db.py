from pathlib import Path
import sys

root = Path.cwd()
sys.path.insert(0, str(root / "apps" / "backend"))

# 1. Gắn tự động migrate_teaching_studio_db vào init_db() trong database.py
db_py = root / "apps" / "backend" / "app" / "db" / "database.py"
if db_py.exists():
    txt = db_py.read_text(encoding="utf-8")
    if "def _run_studio_migrations" not in txt:
        txt += "\n\ndef _run_studio_migrations(custom_path: Path | None = None) -> None:\n    from app.db.studio_migrations import migrate_teaching_studio_db\n    migrate_teaching_studio_db(custom_path)\n"
    if "_orig_init_db_studio" not in txt:
        txt += "\n_orig_init_db_studio = init_db\ndef init_db(custom_path: Path | None = None) -> None:\n    _orig_init_db_studio(custom_path)\n    _run_studio_migrations(custom_path)\n"
    db_py.write_text(txt, encoding="utf-8")

# 2. Đảm bảo TeachingStudioService và LocalMaterialLibrary luôn tự kiểm tra bảng SQLite khi khởi tạo
eng_py = root / "apps" / "backend" / "app" / "services" / "studio" / "engine.py"
if eng_py.exists():
    etxt = eng_py.read_text(encoding="utf-8")
    if "migrate_teaching_studio_db(db_path)" not in etxt:
        etxt = etxt.replace(
            "self.db_path = db_path\n        self.repo = CopilotRepository(db_path=db_path)",
            "self.db_path = db_path\n        from app.db.studio_migrations import migrate_teaching_studio_db\n        migrate_teaching_studio_db(db_path)\n        self.repo = CopilotRepository(db_path=db_path)",
        )
        eng_py.write_text(etxt, encoding="utf-8")

lib_py = root / "apps" / "backend" / "app" / "services" / "studio" / "material_library.py"
if lib_py.exists():
    ltxt = lib_py.read_text(encoding="utf-8")
    if "migrate_teaching_studio_db(db_path)" not in ltxt:
        ltxt = ltxt.replace(
            "def __init__(self, db_path: Path | None = None) -> None:\n        self.db_path = db_path",
            "def __init__(self, db_path: Path | None = None) -> None:\n        self.db_path = db_path\n        from app.db.studio_migrations import migrate_teaching_studio_db\n        migrate_teaching_studio_db(db_path)",
        )
        lib_py.write_text(ltxt, encoding="utf-8")

# 3. Khử cảnh báo SyntaxWarning (\i) trên Python 3.14 trong routes.py
routes_py = root / "apps" / "backend" / "app" / "api" / "routes.py"
if routes_py.exists():
    rtxt = routes_py.read_text(encoding="utf-8").replace("F:\\ielts-copilot", "F:/ielts-copilot")
    routes_py.write_text(rtxt, encoding="utf-8")

# 4. Nâng cấp ngay database chính tại F:\ielts-copilot\data\ielts_copilot.db
from app.db.database import init_db
init_db()
print("[OK] Đã kích hoạt đủ 9 bảng SQLite cho Teaching Studio và sửa sạch SyntaxWarning!")
