"""Guarded local deployment: preserve unrelated Alex changes and a rollback copy."""
from pathlib import Path
from datetime import datetime
import hashlib,json,shutil

stage=Path(__file__).resolve().parents[1]
project=Path(r'D:\HỌC TẬP\dự án trợ lý ảo')
source=project/'trợ lý ảo-local/source/alex-assistant/desktop'
live=project/'trợ lý ảo-local/outputs/Bionic-pet'
guide=project/'Alex-Desktop/ORBIT-DESKTOP.md'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest().upper()
expected=json.loads((stage/'orbit-crisp-before/hashes.json').read_text(encoding='utf-8-sig'))
common=['pet/orbit_scene.py','pet/planet_art.py','pet/planet_surface.py','pet/space_view.py','ORBIT-DESKTOP.md']
extra=['tests/test_space_view.py','tools/verify_orbit.py','tools/deploy_orbit_crisp.py']
for group,root,files in (('source',source,common+extra),('live',live,common)):
    for name in files:
        target=root/name
        if name in expected:
            if not target.is_file() or digest(target)!=expected[name]:
                raise SystemExit('Changed since baseline: '+str(target))
        elif target.exists():
            raise SystemExit('New file already exists; inspect: '+str(target))
if digest(guide)!=expected['ORBIT-DESKTOP.md']: raise SystemExit('Installed guide changed.')
tests=json.loads((stage/'orbit-tests.json').read_text(encoding='utf-8'))
if not tests['passed'] or tests['tests']<32: raise SystemExit('Required tests did not pass.')
# Evidence that the preceding face and music repairs remain untouched.
untouched=['pet/reference_portrait.py','pet/hologram_face.py','pet/app_actions.py','app_action_worker.py']
preserved={name:digest(live/name) for name in untouched}
tag=datetime.now().strftime('%Y%m%d-%H%M%S')
backup=project/'Luu-tru'/('truoc-vu-tru-crisp-'+tag)
report=project/'Bao-cao'/('vu-tru-crisp-'+tag)
backup.mkdir(parents=True,exist_ok=False); report.mkdir(parents=True,exist_ok=False)
changes=[]
for group,root,files in (('source',source,common+extra),('live',live,common)):
    for name in files:
        target=root/name; target.resolve().relative_to(project.resolve())
        old=digest(target) if target.exists() else None
        if old:
            saved=backup/group/name; saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(stage/name,target)
        if digest(target)!=digest(stage/name): raise RuntimeError('Copy verification failed: '+name)
        changes.append({'file':str(target),'before':old,'after':digest(target)})
shutil.copy2(guide,backup/'ORBIT-DESKTOP.md'); shutil.copy2(stage/'ORBIT-DESKTOP.md',guide)
for name,value in preserved.items():
    if digest(live/name)!=value: raise RuntimeError('Unrelated file changed during deployment: '+name)
for name in ('orbit-tests.json','orbit-tests.txt','preview-space.png','preview-space-saturn.png',
             'preview-space-compact.png','ORBIT-DESKTOP.md'):
    shutil.copy2(stage/name,report/name)
(report/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
(report/'preserved.json').write_text(json.dumps(preserved,indent=2),encoding='utf-8')
handoff=project/'ALEX-HANDOFF-CODEX-ANTIGRAVITY.md'
shutil.copy2(handoff,backup/handoff.name)
with handoff.open('a',encoding='utf-8') as f:
    f.write(f'''

## 29/10/2026 — Vũ trụ Alex: bề mặt sắc nét và animation

Thay hình hành tinh vector phẳng bằng shader cầu NumPy cục bộ: texture minh họa,
chiếu sáng, viền khí quyển, vành đai Sao Thổ nhiều lớp. `planet_surface.py` mới;
`planet_art.py` giữ API cũ và chỉ giữ một khung cận cảnh động, tăng độ phân giải theo DPI.
Không phải ảnh NASA hoặc mô phỏng bề mặt chuẩn khoa học. Không thêm dependency.

`orbit_scene.py`: sao nhấp nháy chậm, corona nhẹ, vòng chọn chuyển động; góc nhìn
từ trên được nội suy. `SpacePage` nối cận cảnh vào cùng nhịp hoạt ảnh; pause/hide/
minimize dừng toàn bộ. Nút Hiệu ứng tắt phần trang trí để giảm tải. Camera opt-in giữ nguyên.
Không sửa Android, mic/STT/LLM, lệnh nhạc, đóng/mở ứng dụng, Unlock hay firewall.
Khuôn mặt FatihMakes và sửa music runtime được đối chiếu hash, giữ nguyên.

32 kiểm tra đạt. Cảnh mean/p95 {tests['offscreen_render_ms_mean']}/{tests['offscreen_render_ms_p95']} ms;
cả trang với cận cảnh động {tests['whole_page_animated_mean_ms']}/{tests['whole_page_animated_p95_ms']} ms.
Chưa bật mic/camera thật. Báo cáo `{report.relative_to(project)}`, sao lưu `{backup.relative_to(project)}`.
Trạng thái khởi động lại/giao diện thật xem deployment.json; tài liệu ORBIT-DESKTOP.md đã cập nhật.
''')
result={'report':str(report),'backup':str(backup),'deployed':True,'restart_required':True,
        'live_ui_verified':False,'tests_passed':tests['tests'],'camera_opened':False,'mic_tested':False}
payload=json.dumps(result,ensure_ascii=False,indent=2)
(report/'deployment.json').write_text(payload,encoding='utf-8')
(stage/'orbit-crisp-deployment.json').write_text(payload,encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
