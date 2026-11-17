from __future__ import annotations
import re
from pathlib import Path

PROJECT_ROOT = Path.cwd()
HTML_PATH = PROJECT_ROOT / "apps" / "desktop" / "index.html"

EXPERT_CSS = """
    :root {
      --bg: #f8fafc;
      --panel: #ffffff;
      --panel-alt: #f1f5f9;
      --surface-subtle: #f8fafc;
      --surface-hover: #f1f5f9;
      --text: #0f172a;
      --text-secondary: #334155;
      --muted: #64748b;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-soft: rgba(37, 99, 235, 0.08);
      --success: #059669;
      --success-soft: rgba(5, 150, 105, 0.1);
      --warning: #d97706;
      --warning-soft: rgba(217, 119, 6, 0.1);
      --danger: #dc2626;
      --danger-soft: rgba(220, 38, 38, 0.08);
      --border: #e2e8f0;
      --border-strong: #cbd5e1;
      --shadow-sm: 0 1px 2px 0 rgba(15, 23, 42, 0.04);
      --shadow-md: 0 4px 12px -2px rgba(15, 23, 42, 0.06), 0 2px 4px -2px rgba(15, 23, 42, 0.03);
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 12px;
    }

    [data-theme="dark"] {
      --bg: #0b0f19;
      --panel: #111827;
      --panel-alt: #1e293b;
      --surface-subtle: #0f172a;
      --surface-hover: #1e293b;
      --text: #f8fafc;
      --text-secondary: #cbd5e1;
      --muted: #94a3b8;
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --primary-soft: rgba(59, 130, 246, 0.14);
      --success: #10b981;
      --success-soft: rgba(16, 185, 129, 0.14);
      --warning: #f59e0b;
      --warning-soft: rgba(245, 158, 11, 0.14);
      --danger: #ef4444;
      --danger-soft: rgba(239, 68, 68, 0.14);
      --border: #1e293b;
      --border-strong: #334155;
      --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.3);
      --shadow-md: 0 4px 16px -2px rgba(0, 0, 0, 0.4);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
      font-size: 14px;
      -webkit-font-smoothing: antialiased;
      padding-bottom: 56px;
      transition: background-color 0.15s ease, color 0.15s ease;
    }

    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
      height: 58px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 40;
      box-shadow: var(--shadow-sm);
    }
    .brand { display: flex; align-items: center; gap: 12px; }
    .brand h1 {
      font-size: 1.05rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .brand h1::before {
      content: "";
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 3px;
      background: var(--primary);
    }

    .nav-tabs {
      display: flex;
      align-items: center;
      gap: 4px;
      background: var(--panel-alt);
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .tab-btn {
      background: transparent;
      color: var(--muted);
      border: none;
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.84rem;
      transition: all 0.12s ease;
      white-space: nowrap;
    }
    .tab-btn:hover { color: var(--text); }
    .tab-btn.active {
      background: var(--panel);
      color: var(--primary);
      box-shadow: var(--shadow-sm);
    }

    .container { max-width: 1440px; margin: 20px auto; padding: 0 24px; }
    .grid-2 { display: grid; grid-template-columns: 1fr 1.12fr; gap: 20px; align-items: start; }
    .row-3 { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 12px; }

    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 20px;
      margin-bottom: 16px;
      box-shadow: var(--shadow-sm);
    }
    .card h2 {
      font-size: 0.96rem;
      font-weight: 600;
      letter-spacing: -0.01em;
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .card h3 {
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 10px;
    }

    label {
      display: block;
      font-size: 0.78rem;
      color: var(--text-secondary);
      margin-bottom: 5px;
      font-weight: 600;
      letter-spacing: 0.01em;
    }
    input[type="text"], input[type="number"], input[type="file"], select, textarea {
      width: 100%;
      background: var(--surface-subtle);
      border: 1px solid var(--border-strong);
      color: var(--text);
      padding: 8px 11px;
      border-radius: var(--radius-sm);
      font-size: 0.875rem;
      margin-bottom: 12px;
      font-family: inherit;
      transition: border-color 0.12s ease, box-shadow 0.12s ease;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 3px var(--primary-soft);
      background: var(--panel);
    }
    textarea { resize: vertical; line-height: 1.5; }

    .badge {
      font-size: 0.72rem;
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--text-secondary);
      border: 1px solid var(--border);
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .badge.online {
      background: var(--success-soft);
      color: var(--success);
      border-color: rgba(5, 150, 105, 0.25);
    }
    .badge.assumed {
      background: var(--warning-soft);
      color: var(--warning);
      border-color: rgba(217, 119, 6, 0.25);
    }
    .badge.explicit {
      background: var(--success-soft);
      color: var(--success);
      border-color: rgba(5, 150, 105, 0.25);
    }

    .btn {
      background: var(--primary);
      color: #ffffff;
      border: 1px solid transparent;
      padding: 8px 14px;
      border-radius: var(--radius-sm);
      font-weight: 600;
      cursor: pointer;
      font-size: 0.84rem;
      transition: all 0.12s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    .btn:hover { background: var(--primary-hover); }
    .btn:disabled { opacity: 0.55; cursor: not-allowed; }
    .btn-secondary {
      background: var(--panel);
      color: var(--text-secondary);
      border: 1px solid var(--border-strong);
    }
    .btn-secondary:hover {
      background: var(--surface-hover);
      color: var(--text);
      border-color: var(--muted);
    }
    .btn-success { background: var(--success); color: #ffffff; }
    .btn-success:hover { filter: brightness(0.95); }
    .btn-danger {
      background: var(--danger-soft);
      color: var(--danger);
      border: 1px solid rgba(220, 38, 38, 0.2);
    }
    .btn-danger:hover { background: var(--danger); color: #ffffff; }
    .btn-sm { padding: 5px 10px; font-size: 0.78rem; }

    .score-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 16px; }
    .score-box {
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 12px 8px;
      text-align: center;
    }
    .score-box.overall { border-color: var(--primary); background: var(--primary-soft); }
    .score-box .label {
      font-size: 0.7rem;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .score-box .val { font-size: 1.4rem; font-weight: 700; margin-top: 2px; color: var(--text); }
    .score-box.overall .val { color: var(--primary); }

    .essay-preview {
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px;
      white-space: pre-wrap;
      font-size: 0.92rem;
      line-height: 1.75;
      max-height: 460px;
      overflow-y: auto;
      color: var(--text);
    }
    mark.hl {
      background: var(--warning-soft);
      color: var(--text);
      padding: 2px 4px;
      border-radius: 4px;
      border-bottom: 2px solid var(--warning);
      font-weight: 600;
    }

    .crit-section { border-top: 1px solid var(--border); padding-top: 12px; margin-top: 12px; }
    .crit-title {
      font-weight: 600;
      font-size: 0.88rem;
      color: var(--text);
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
    }
    .ev-item {
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-left: 3px solid var(--warning);
      padding: 10px 12px;
      border-radius: var(--radius-sm);
      margin-bottom: 8px;
      cursor: pointer;
      font-size: 0.84rem;
      transition: background-color 0.12s ease;
    }
    .ev-item:hover { background: var(--surface-hover); }
    .ev-quote { font-style: italic; color: var(--text-secondary); margin-bottom: 4px; font-weight: 500; }
    .ev-fix { color: var(--success); font-weight: 600; margin-top: 4px; }

    table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); text-align: left; }
    th {
      color: var(--muted);
      font-weight: 600;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      background: var(--surface-subtle);
    }
    tbody tr:hover { background: var(--surface-hover); }

    #studioStageBar {
      display: grid;
      grid-template-columns: repeat(7, 1fr);
      gap: 6px;
      margin-top: 12px;
    }
    #studioStageBar .tab-btn {
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      color: var(--muted);
      padding: 8px 10px;
      border-radius: var(--radius-sm);
      font-size: 0.78rem;
      font-weight: 600;
      text-align: left;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    #studioStageBar .tab-btn:hover { border-color: var(--border-strong); color: var(--text); }
    #studioStageBar .tab-btn.active {
      background: var(--primary-soft);
      border-color: var(--primary);
      color: var(--primary);
      box-shadow: none;
    }

    details.ui-accordion {
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      margin-bottom: 10px;
      overflow: hidden;
      transition: border-color 0.12s ease;
    }
    details.ui-accordion[open] {
      background: var(--panel);
      border-color: var(--border-strong);
      box-shadow: var(--shadow-sm);
    }
    details.ui-accordion > summary {
      list-style: none;
      cursor: pointer;
      padding: 12px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      font-weight: 600;
      font-size: 0.88rem;
      user-select: none;
      background: var(--surface-subtle);
    }
    details.ui-accordion > summary::-webkit-details-marker { display: none; }
    details.ui-accordion > summary:hover { background: var(--surface-hover); }
    .acc-body { padding: 16px; border-top: 1px solid var(--border); background: var(--panel); }
    .meta-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }
    .info-block {
      background: var(--surface-subtle);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 10px 12px;
      font-size: 0.83rem;
    }
    .info-block b {
      display: block;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: var(--muted);
      margin-bottom: 4px;
    }

    #uiToast {
      position: fixed;
      bottom: 20px;
      right: 24px;
      background: var(--text);
      color: var(--bg);
      padding: 10px 16px;
      border-radius: var(--radius-sm);
      font-size: 0.84rem;
      font-weight: 600;
      box-shadow: var(--shadow-md);
      z-index: 100;
      opacity: 0;
      transform: translateY(8px);
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.18s ease;
    }
    #uiToast.show { opacity: 1; transform: translateY(0); }
    .hidden { display: none !important; }
"""

def upgrade_html(raw_html: str) -> str:
    html = raw_html
    html = re.sub(r"<style>.*?</style>", f"<style>{EXPERT_CSS}\n  </style>", html, count=1, flags=re.S)

    inline_replacements = [
        ("background:#0f172a;", "background:var(--surface-subtle);"),
        ("background: #0f172a;", "background:var(--surface-subtle);"),
        ("background:#172554;", "background:var(--primary-soft);"),
        ("color:#fde047;", "color:var(--warning);"),
        ("color:#4ade80;", "color:var(--success);"),
        ("background:#78350f; color:#fde047;", "background:var(--warning-soft); color:var(--warning);"),
        ("background:rgba(34,197,94,0.2); color:#4ade80;", "background:var(--success-soft); color:var(--success);"),
        ("background:rgba(34,197,94,0.08);", "background:var(--success-soft);"),
        ("background:rgba(245,158,11,0.08);", "background:var(--warning-soft);"),
        ("background:rgba(239,68,68,0.12); color:#fca5a5;", "background:var(--danger-soft); color:var(--danger);"),
    ]
    for old_s, new_s in inline_replacements:
        html = html.replace(old_s, new_s)

    emoji_cleanup = [
        ("🗑 Xóa Giáo án", "Xóa giáo án"),
        ("⏹ Hủy tác vụ AI", "Hủy tác vụ"),
        ("⚡ Sinh / Tái tạo Playbook", "Sinh Playbook"),
        ("⬇ Xuất DOCX Playbook", "Xuất DOCX"),
        ("⬇ Xuất PDF Playbook", "Xuất PDF"),
        ("⚡ Sinh Handout & Teacher Guide", "Sinh Handout & Guide"),
        ("⬇ Xuất DOCX Student Handout", "Xuất DOCX Handout"),
        ("⬇ Xuất PDF Student Handout", "Xuất PDF Handout"),
        ("⬇ Xuất DOCX Teacher Guide", "Xuất DOCX Guide"),
        ("⬇ Xuất PDF Teacher Guide", "Xuất PDF Guide"),
        ("⬇ Xuất DOCX Answer Key", "Xuất DOCX Answer Key"),
        ("⬇ Xuất PDF Answer Key", "Xuất PDF Answer Key"),
        ("⬇ Xuất DOCX Summary", "Xuất DOCX"),
        ("⬇ Xuất PDF Summary", "Xuất PDF"),
        ("🔄 Đồng bộ Phiên dạy", "Đồng bộ phiên"),
        ("💾 Lưu chỉnh sửa", "Lưu"),
        ("🔄 Tạo lại mục này", "Tạo lại bằng AI"),
        ("💾 Lưu bài tập", "Lưu"),
        ("⬇ Tạo lại Dễ hơn", "Giảm độ khó"),
        ("⬆ Tạo lại Khó hơn", "Tăng độ khó"),
        ("💾 Lưu Đáp án", "Lưu đáp án"),
        ("🗑 Xóa Học viên", "Xóa học viên"),
        ("🗑 Xóa bài", "Xóa"),
        ("💾 Backup DB", "Sao lưu DB"),
        ("🧩 ", ""),
        ("🚀 ", ""),
        ("🔍 ", ""),
        ("⏱ ", ""),
        ("💡 ", ""),
        ("⚖ ", ""),
        ("❓ ", ""),
    ]
    for old_e, new_e in emoji_cleanup:
        html = html.replace(old_e, new_e)

    if 'id="themeToggleBtn"' not in html:
        html = html.replace(
            'onclick="triggerBackup()">Sao lưu DB</button>',
            'onclick="triggerBackup()">Sao lưu DB</button>\n      <button class="tab-btn" id="themeToggleBtn" onclick="toggleUiTheme()">Giao diện: Sáng</button>',
        )

    if 'id="uiToast"' not in html:
        html = html.replace("</body>", '  <div id="uiToast"></div>\n</body>')

    alert_to_toast = [
        ("alert('✓ Đã lưu bản duyệt Giáo án thành công!');", "showToast('Đã lưu bản duyệt giáo án');"),
        ("alert('✓ Đã lưu chỉnh sửa hoạt động và tính lại tổng thời lượng Playbook!');", "showToast('Đã lưu hoạt động & cập nhật thời lượng');"),
        ("alert('✓ Đã lưu bài tập (đã kiểm duyệt không rò rỉ đáp án)!');", "showToast('Đã lưu bài tập Handout');"),
        ("alert(`✓ Đã lưu cập nhật Đáp án cho Exercise #${exOrder}!`);", "showToast(`Đã lưu đáp án Bài tập #${exOrder}`);"),
        ("alert('✓ Đã cập nhật nhận xét sau buổi học vào Hồ sơ học viên!');", "showToast('Đã cập nhật vào Hồ sơ học viên');"),
        ("alert('Đã tạo hồ sơ học viên thành công!');", "showToast('Đã tạo hồ sơ học viên mới');"),
    ]
    for old_a, new_t in alert_to_toast:
        html = html.replace(old_a, new_t)

    accordion_js_override = """
    // ================= EXPERT UI OVERRIDES: THEME, TOAST & ACCORDION RENDERERS =================
    function showToast(msg) {
      const t = document.getElementById('uiToast');
      if (!t) return;
      t.textContent = msg;
      t.classList.add('show');
      clearTimeout(window._toastTimer);
      window._toastTimer = setTimeout(() => t.classList.remove('show'), 2800);
    }

    function toggleUiTheme() {
      const root = document.documentElement;
      const curr = root.getAttribute('data-theme') || 'light';
      const next = curr === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      localStorage.setItem('ielts_copilot_theme', next);
      const btn = document.getElementById('themeToggleBtn');
      if (btn) btn.textContent = next === 'dark' ? 'Giao diện: Tối' : 'Giao diện: Sáng';
    }

    (function initSavedTheme() {
      const saved = localStorage.getItem('ielts_copilot_theme') || 'light';
      document.documentElement.setAttribute('data-theme', saved);
      window.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('themeToggleBtn');
        if (btn) btn.textContent = saved === 'dark' ? 'Giao diện: Tối' : 'Giao diện: Sáng';
      });
    })();

    function toggleAllAccordions(containerId, openState) {
      const box = document.getElementById(containerId);
      if (!box) return;
      box.querySelectorAll('details.ui-accordion').forEach(d => { d.open = openState; });
    }

    renderStage3Playbook = function(plan) {
      const pb = plan.playbook;
      const banner = document.getElementById('pbDurationBanner');
      const box = document.getElementById('pbActivitiesContainer');
      const appText = document.getElementById('pbApproachText');

      if (!pb) {
        appText.textContent = 'Chưa sinh Teaching Playbook. Bấm "Sinh Playbook" ở góc phải để bắt đầu.';
        banner.innerHTML = 'Chưa có dữ liệu kiểm tra thời lượng.';
        box.innerHTML = '';
        return;
      }

      appText.textContent = `Chiến lược sư phạm: ${pb.pedagogical_approach}`;
      const dv = pb.duration_validation || {};
      const recs = pb.time_shortening_recommendations || [];
      if (dv.exceeds_available_time) {
        banner.style.borderColor = 'var(--warning)';
        banner.innerHTML = `<b style="color:var(--warning);">Cảnh báo vượt thời lượng (${dv.total_allocated_minutes}/${dv.lesson_duration_minutes} phút — vượt ${dv.overflow_minutes} phút):</b><br/>` +
          recs.map(r => `• ${escapeHtml(r)}`).join('<br/>');
      } else {
        banner.style.borderColor = 'var(--border)';
        banner.innerHTML = `<b style="color:var(--success);">Phân bổ thời gian chuẩn:</b> Tổng ${dv.total_allocated_minutes}/${dv.lesson_duration_minutes} phút (Hoạt động: ${dv.activities_sum_minutes} phút + Chuyển tiếp: ${dv.transition_buffer_minutes} phút).`;
      }

      const controls = `<div style="display:flex; justify-content:flex-end; gap:8px; margin-bottom:10px;">
        <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions('pbActivitiesContainer', true)">Mở rộng tất cả</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions('pbActivitiesContainer', false)">Thu gọn tất cả</button>
      </div>`;

      box.innerHTML = controls + (plan.activities || []).map((act, idx) => {
        const exPairs = (act.examples_counterexamples || []).map(p =>
          `<div style="margin-bottom:6px;"><span class="badge explicit">Strong</span> "${escapeHtml(p.strong_example)}"<br/><span class="badge assumed">Weak</span> "${escapeHtml(p.weak_counterexample)}" <span style="color:var(--muted);">(${escapeHtml(p.comparison_point)})</span></div>`
        ).join('');
        return `
          <details class="ui-accordion" ${idx === 0 ? 'open' : ''}>
            <summary>
              <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                <span class="badge">Hoạt động ${act.activity_order}</span>
                <span>${escapeHtml(act.title)}</span>
                <span class="badge">${act.duration_minutes} phút</span>
                <span class="badge">${escapeHtml(act.priority_level)}</span>
              </div>
              <span style="font-size:0.78rem; color:var(--muted);">Bấm để đóng/mở chi tiết</span>
            </summary>
            <div class="acc-body">
              <div class="row-3" style="grid-template-columns: 2.2fr 0.8fr auto; align-items:end; margin-bottom:10px;">
                <div>
                  <label>Tiêu đề hoạt động</label>
                  <input type="text" id="actTitle_${act.id}" value="${escapeHtml(act.title)}" style="margin:0;" />
                </div>
                <div>
                  <label>Thời lượng (phút)</label>
                  <input type="number" id="actDur_${act.id}" value="${act.duration_minutes}" style="margin:0;" />
                </div>
                <div style="display:flex; gap:6px;">
                  <button class="btn btn-secondary btn-sm" onclick="saveSinglePlaybookActivity('${act.id}')">Lưu</button>
                  <button class="btn btn-secondary btn-sm" onclick="regenerateSinglePlaybookActivity('${act.id}')">Tạo lại mục này</button>
                </div>
              </div>
              <div style="font-size:0.84rem; color:var(--muted); margin-bottom:10px;">
                <b>Mục tiêu:</b> ${escapeHtml(act.learning_objective)} · <b>Lý do sư phạm:</b> ${escapeHtml(act.teaching_rationale || '')}
              </div>
              <label>Lời dẫn & Hướng dẫn chi tiết cho Giáo viên</label>
              <textarea id="actInstr_${act.id}" rows="2">${escapeHtml(act.teacher_instructions || '')}</textarea>
              <div class="meta-grid-2">
                <div class="info-block">
                  <b>Trình tự giảng giải</b>
                  ${(act.explanation_sequence || []).map((s, i) => `${i+1}.${escapeHtml(s)}`).join('<br/>')}
                </div>
                <div class="info-block">
                  <b>Ví dụ chuẩn vs. Phản ví dụ</b>
                  ${exPairs || 'Chưa có'}
                </div>
                <div class="info-block">
                  <b>Câu hỏi kiểm tra (CCQs) & Đáp án kỳ vọng</b>
                  ${(act.teacher_questions || []).map(q => `• Q: ${escapeHtml(q)}`).join('<br/>')}<br/>
                  ${(act.expected_student_responses || []).map(r => `→ A: ${escapeHtml(r)}`).join('<br/>')}
                </div>
                <div class="info-block">
                  <b>Ngộ nhận thường gặp & Phân hóa học viên</b>
                  <b>Ngộ nhận:</b> ${(act.common_misconceptions || []).map(escapeHtml).join('; ')}<br/>
                  <b>Scaffolding (Học viên yếu):</b> ${escapeHtml(act.scaffolding_struggling || '')}<br/>
                  <b>Extension (Học viên khá):</b> ${escapeHtml(act.extension_fast_learners || '')}
                </div>
              </div>
            </div>
          </details>
        `;
      }).join('');
    };

    renderStage4Handout = function(plan) {
      const ho = plan.handout;
      const sumBox = document.getElementById('hoPersonalizationSummary');
      const exBox = document.getElementById('hoExercisesContainer');
      const metaBox = document.getElementById('hoFooterMetaBox');

      if (!ho) {
        sumBox.textContent = 'Chưa sinh Student Handout. Bấm "Sinh Handout & Guide" để tạo.';
        exBox.innerHTML = '';
        metaBox.innerHTML = '';
        return;
      }

      sumBox.textContent = ho.personalization_summary || 'Không áp dụng cá nhân hóa.';
      document.getElementById('hoPersonalizeCheck').checked = Boolean(ho.personalization_applied);

      const controls = `<div style="display:flex; justify-content:flex-end; gap:8px; margin-bottom:10px;">
        <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions('hoExercisesContainer', true)">Mở rộng tất cả</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions('hoExercisesContainer', false)">Thu gọn tất cả</button>
      </div>`;

      exBox.innerHTML = controls + (ho.exercises || []).map((ex, idx) => `
        <details class="ui-accordion" ${idx === 0 ? 'open' : ''}>
          <summary>
            <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
              <span class="badge">Bài tập ${ex.exercise_order}</span>
              <span>${escapeHtml(ex.title)}</span>
              <span class="badge">${escapeHtml(ex.progression_stage)}</span>
              <span class="badge">${escapeHtml(ex.difficulty_level)}</span>
            </div>
            <span style="font-size:0.78rem; color:var(--muted);">Bấm để chỉnh sửa</span>
          </summary>
          <div class="acc-body">
            <div style="display:flex; justify-content:space-between; align-items:end; gap:10px; margin-bottom:10px;">
              <div style="flex:1;">
                <label>Tiêu đề bài tập</label>
                <input type="text" id="exTitle_${ex.id}" value="${escapeHtml(ex.title)}" style="margin:0;" />
              </div>
              <div style="display:flex; gap:6px;">
                <button class="btn btn-secondary btn-sm" onclick="saveSingleHandoutExercise('${ex.id}')">Lưu</button>
                <button class="btn btn-secondary btn-sm" onclick="regenerateSingleHandoutExercise('${ex.id}', 'easier')">Giảm độ khó</button>
                <button class="btn btn-secondary btn-sm" onclick="regenerateSingleHandoutExercise('${ex.id}', 'harder')">Tăng độ khó</button>
              </div>
            </div>
            <div style="font-size:0.82rem; color:var(--muted); margin-bottom:8px;">
              <b>Mục tiêu:</b> ${escapeHtml(ex.learning_objective)} · <b>Định dạng trả lời:</b> ${escapeHtml(ex.expected_response_format)}
            </div>
            <label>Hướng dẫn dành cho Học viên (Student Instructions)</label>
            <textarea id="exInstr_${ex.id}" rows="2">${escapeHtml(ex.student_instructions)}</textarea>
            <label>Ngữ liệu câu hỏi (Mỗi câu 1 dòng — Không chứa đáp án)</label>
            <textarea id="exItems_${ex.id}" rows="3" style="margin-bottom:0;">${escapeHtml((ex.content_items || []).join('\\n'))}</textarea>
          </div>
        </details>
      `).join('');

      const checkItems = (ho.self_assessment_checklist || []).map(c => `<li>[ ] ${escapeHtml(c)}</li>`).join('');
      metaBox.innerHTML = `
        <div class="info-block" style="margin-top:12px;">
          <b>Checklist Tự đánh giá & Bài tập về nhà</b>
          <ul style="margin-left:16px; margin-bottom:8px;">${checkItems}</ul>
          <div><b>Exit Ticket:</b> ${escapeHtml(ho.exit_ticket_prompt || '')}</div>
          <div style="margin-top:4px;"><b>Homework:</b> ${escapeHtml(ho.homework_assignment || '')}</div>
        </div>
      `;
    };

    renderStage5TeacherGuide = function(plan) {
      const tg = plan.teacher_guide;
      const box = document.getElementById('tgAnswerKeysContainer');
      const chkBox = document.getElementById('tgObjectiveChecklistBox');
      if (!tg) {
        box.innerHTML = '<div style="color:var(--muted);">Chưa sinh Teacher Guide. Hãy sinh bộ học liệu ở Bước 4 trước.</div>';
        chkBox.innerHTML = '';
        return;
      }

      const controls = `<div style="display:flex; justify-content:flex-end; gap:8px; margin-bottom:10px;">
        <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions('tgAnswerKeysContainer', true)">Mở rộng tất cả</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleAllAccordions('tgAnswerKeysContainer', false)">Thu gọn tất cả</button>
      </div>`;

      box.innerHTML = controls + (tg.answer_keys || []).map((k, idx) => `
        <details class="ui-accordion" ${idx === 0 ? 'open' : ''}>
          <summary>
            <div style="display:flex; align-items:center; gap:10px;">
              <span class="badge assumed">Đáp án Bài ${k.exercise_order}</span>
              <span>${escapeHtml(k.exercise_title)}</span>
            </div>
            <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); saveTeacherKeyItem('${tg.id}', ${k.exercise_order})">Lưu đáp án</button>
          </summary>
          <div class="acc-body">
            <label>Đáp án chuẩn (Mỗi ý 1 dòng)</label>
            <textarea id="tgAns_${k.exercise_order}" rows="2">${escapeHtml((k.correct_answers || []).join('\\n'))}</textarea>
            <label>Giải thích lý do & Gợi ý sửa lỗi cho học viên</label>
            <textarea id="tgExp_${k.exercise_order}" rows="2">${escapeHtml(k.explanation_why || '')}</textarea>
            <div class="grid-2" style="gap:10px;">
              <div>
                <label>Phương án chấp nhận được khác</label>
                <textarea id="tgAlt_${k.exercise_order}" rows="2">${escapeHtml((k.alternative_acceptable_answers || []).join('\\n'))}</textarea>
              </div>
              <div>
                <label>Tiêu chí chấm bài mở</label>
                <textarea id="tgCrit_${k.exercise_order}" rows="2">${escapeHtml((k.open_ended_marking_criteria || []).join('\\n'))}</textarea>
              </div>
            </div>
            <label>Câu trả lời mẫu minh họa <span class="badge assumed">Illustrative LLM Example — Non-Official</span></label>
            <textarea id="tgSample_${k.exercise_order}" rows="2" style="margin-bottom:0;">${escapeHtml(k.illustrative_sample_response || '')}</textarea>
          </div>
        </details>
      `).join('');

      chkBox.innerHTML = `
        <div class="info-block">
          <b>Checklist Đánh giá Mục tiêu Bài học (Dành cho Giáo viên)</b>
          <ul style="margin-left:16px;">
            ${(tg.objective_evaluation_checklist || []).map(c => `<li>[ ] ${escapeHtml(c)}</li>`).join('')}
          </ul>
        </div>
      `;
    };
"""

    if "EXPERT UI OVERRIDES" not in html:
        html = html.replace("</script>", accordion_js_override + "\n  </script>")

    return html

if __name__ == "__main__":
    if not HTML_PATH.exists():
        raise SystemExit(f"Không tìm thấy {HTML_PATH}")
    updated = upgrade_html(HTML_PATH.read_text(encoding="utf-8"))
    HTML_PATH.write_text(updated, encoding="utf-8")
    print("[OK] Đã nâng cấp giao diện IELTS Copilot chuẩn Expert UI (Sáng/Tối + Accordion gọn gàng)!")
