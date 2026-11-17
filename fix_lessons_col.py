from pathlib import Path
import re

root = Path.cwd()

# 1. Bỏ lệnh ghi thừa vào bảng lessons cũ trong engine.py (dùng bảng lesson_plans độc lập)
eng_py = root / "apps" / "backend" / "app" / "services" / "studio" / "engine.py"
etxt = eng_py.read_text(encoding="utf-8")
etxt = re.sub(
    r"legacy_id = str\(uuid\.uuid4\(\)\)\s+ts = now_iso\(\)\s+final_title = req\.title\.strip\(\) or analyzed\.title\s+with db_session\(self\.db_path\) as conn:\s+conn\.execute\(\s+\"\"\"\s+INSERT INTO lessons.*?\),\s+\)",
    "legacy_id = None\n        ts = now_iso()\n        final_title = req.title.strip() or analyzed.title\n\n        with db_session(self.db_path) as conn:",
    etxt,
    flags=re.S,
)
etxt = re.sub(
    r"if existing\.get\(\"legacy_lesson_id\"\):\s+conn\.execute\(\s+\"UPDATE lessons SET title = \?,.*?\),\s+\)",
    "",
    etxt,
    flags=re.S,
)
eng_py.write_text(etxt, encoding="utf-8")

# 2. Khử nốt cảnh báo SyntaxWarning (\d) trong docstring của routes.py
routes_py = root / "apps" / "backend" / "app" / "api" / "routes.py"
if routes_py.exists():
    rtxt = routes_py.read_text(encoding="utf-8").replace("\\data\\", "/data/")
    routes_py.write_text(rtxt, encoding="utf-8")

print("[OK] Đã cập nhật xong engine.py và routes.py!")
