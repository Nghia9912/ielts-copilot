from pathlib import Path

PROJECT_ROOT = Path.cwd()
APP_DIR = PROJECT_ROOT / "apps" / "backend" / "app"
DESKTOP_DIR = PROJECT_ROOT / "apps" / "desktop"

# 1. Bổ sung API Xóa Học viên, Xóa từng Bài nộp & Backup DB vào routes.py
routes_path = APP_DIR / "api" / "routes.py"
r_text = routes_path.read_text(encoding="utf-8")

if '@router.delete("/students/{student_id}")' not in r_text:
    r_text += '''

import shutil
from datetime import datetime
from app.core.config import DB_PATH, DATA_DIR


@router.delete("/students/{student_id}")
def delete_student_and_files(student_id: str):
    student = repo.get_student(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Không tìm thấy học viên.")
    from app.db.database import db_session
    removed_audio_files = 0
    with db_session() as conn:
        audio_rows = conn.execute(
            "SELECT source_audio_path FROM submissions WHERE student_id = ? AND source_audio_path IS NOT NULL",
            (student_id,),
        ).fetchall()
        for r in audio_rows:
            try:
                p = validate_and_resolve_audio_path(r["source_audio_path"])
                if p.exists():
                    p.unlink()
                    removed_audio_files += 1
            except Exception:
                pass
        conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    return {"status": "deleted", "student_id": student_id, "removed_audio_files": removed_audio_files}


@router.post("/system/backup")
def create_database_backup():
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"ielts_copilot_backup_{stamp}.db"
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_file)
    backups = sorted([f.name for f in backup_dir.glob("*.db")], reverse=True)
    return {"status": "ok", "backup_created": backup_file.name, "available_backups": backups}
'''

if '@router.delete("/submissions/{submission_id}")' not in r_text:
    r_text += '''

@router.delete("/submissions/{submission_id}")
def delete_single_submission(submission_id: str):
    sub = repo.get_submission(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài nộp.")
    from app.db.database import db_session
    if sub.get("source_audio_path"):
        try:
            p = validate_and_resolve_audio_path(sub["source_audio_path"])
            if p.exists():
                p.unlink()
        except Exception:
            pass
    with db_session() as conn:
        conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
    return {"status": "deleted", "submission_id": submission_id}
'''

routes_path.write_text(r_text, encoding="utf-8")

# 2. Bổ sung nút Xóa Học viên, Xóa từng Bài nộp & Backup DB vào giao diện index.html
html_path = DESKTOP_DIR / "index.html"
html = html_path.read_text(encoding="utf-8")

if "triggerBackup()" not in html:
    html = html.replace(
        '<button class="tab-btn" onclick="switchTab(\'students\')">3. Student Records</button>',
        '<button class="tab-btn" onclick="switchTab(\'students\')">3. Student Records</button>\n'
        '      <button class="tab-btn" style="color:#4ade80;" onclick="triggerBackup()">💾 Backup DB</button>',
    )

old_header = '<select id="progressStudentSelect" style="width:280px; margin:0;" onchange="loadStudentProgress()"></select>'
new_header = '''<div style="display:flex; gap:8px; align-items:center;">
                <select id="progressStudentSelect" style="width:280px; margin:0;" onchange="loadStudentProgress()"></select>
                <button class="btn btn-danger" style="padding:8px 12px; font-size:0.82rem;" onclick="deleteCurrentStudent()">🗑 Xóa Học viên</button>
              </div>'''
if "deleteCurrentStudent()" not in html and old_header in html:
    html = html.replace(old_header, new_header)

old_btn_1 = '''<button class="btn btn-secondary" style="padding:4px 10px; font-size:0.8rem;" onclick="openSubmissionInLab('${row.submission_id}', '${row.assessment_id || ''}')">Mở lại</button>'''
old_btn_2 = '''<button class="btn btn-secondary" style="padding:4px 10px; font-size:0.8rem;" onclick="openSubmissionInLab('${row.submission_id}', '${row.assessment_id || ''}')">Mở lại bài</button>'''
new_btns = '''<div style="display:flex; gap:6px;">
              <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.8rem;" onclick="openSubmissionInLab('${row.submission_id}', '${row.assessment_id || ''}')">Mở lại</button>
              <button class="btn btn-danger" style="padding:4px 10px; font-size:0.8rem;" onclick="deleteSubmission('${row.submission_id}')">🗑 Xóa bài</button>
            </div>'''

if "deleteSubmission(" not in html:
    if old_btn_1 in html:
        html = html.replace(old_btn_1, new_btns)
    elif old_btn_2 in html:
        html = html.replace(old_btn_2, new_btns)

js_funcs = '''
    async function triggerBackup() {
      try {
        const res = await api('/api/system/backup', { method: 'POST' });
        alert(`✓ Đã tạo bản sao lưu Database an toàn tại:\\nF:\\\\ielts-copilot\\\\data\\\\backups\\\\${res.backup_created}`);
      } catch (e) {
        alert('Lỗi khi sao lưu Database: ' + e.message);
      }
    }

    async function deleteCurrentStudent() {
      const sel = document.getElementById('progressStudentSelect');
      const studentId = sel.value;
      if (!studentId) return alert('Chưa có học viên nào để xóa!');
      const studentName = sel.options[sel.selectedIndex].text;
      if (!confirm(`Bạn có chắc chắn muốn XÓA VĨNH VIỄN học viên "${studentName}" cùng toàn bộ bài viết, bài nói và file ghi âm của học viên này không?`)) {
        return;
      }
      try {
        const res = await api(`/api/students/${studentId}`, { method: 'DELETE' });
        alert(`✓ Đã xóa học viên và dọn sạch ${res.removed_audio_files || 0} file ghi âm trên ổ đĩa!`);
        document.getElementById('recurringErrorsBox').innerHTML = '<div style="color:var(--muted); font-size:0.88rem;">Chưa có học viên hoặc dữ liệu.</div>';
        document.getElementById('historyTableBody').innerHTML = '';
        await loadStudentsList();
      } catch (e) {
        alert('Lỗi khi xóa học viên: ' + e.message);
      }
    }

    async function deleteSubmission(submissionId) {
      if (!confirm('Bạn có chắc muốn xóa vĩnh viễn bài nộp này (kèm kết quả chấm và file ghi âm nếu có) không?')) {
        return;
      }
      try {
        await api(`/api/submissions/${submissionId}`, { method: 'DELETE' });
        await loadStudentProgress();
      } catch (e) {
        alert('Lỗi khi xóa bài nộp: ' + e.message);
      }
    }
'''

if "async function deleteCurrentStudent()" not in html:
    html = html.replace("async function openSubmissionInLab(", js_funcs + "\n    async function openSubmissionInLab(")

html_path.write_text(html, encoding="utf-8")
print("[OK] Đã cập nhật thành công nút Xóa Học viên, Xóa từng Bài nộp và Backup Database!")
