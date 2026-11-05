"""One-time, guarded source/live deployment. No process termination or UI actions."""
from pathlib import Path
import hashlib
import json
import shutil
from datetime import datetime

stage=Path(__file__).resolve().parents[1]
project=Path(r'D:\HỌC TẬP\dự án trợ lý ảo')
repo=project/'trợ lý ảo-local/source/alex-assistant/desktop'
live=project/'trợ lý ảo-local/outputs/Bionic-pet'
expected='1A9D1AA0F3D9ACFB667E462EF6D579BCD1D0BCC3E71D4E4C6FDA9C0BD41A0BEB'
digest=lambda p: hashlib.sha256(p.read_bytes()).hexdigest().upper()
for root in (repo,live):
    if digest(root/'pet/app_window.py') != expected:
        raise SystemExit('Source changed since review. Stop and inspect before deployment.')
if not json.loads((stage/'orbit-tests.json').read_text())['passed']:
    raise SystemExit('Tests did not pass')
tag=datetime.now().strftime('%Y%m%d-%H%M%S')
backup=project/'Luu-tru'/('truoc-alex-orbit-'+tag)
report=project/'Bao-cao'/('alex-orbit-'+tag)
backup.mkdir(parents=True,exist_ok=False); report.mkdir(parents=True,exist_ok=False)
common=['pet/app_window.py','pet/command_center.py','pet/space_view.py','pet/orbit_math.py',
        'pet/gesture_worker.py','assets/gestures/hand_landmarker.task',
        'requirements-gestures.lock.txt','ORBIT-DESKTOP.md']
extra=['tests/test_space_view.py','tests/test_camera_session.py',
       'tools/verify_orbit.py','tools/preview_orbit.py','tools/deploy_orbit.py']
changes=[]
for group,root,files in [('source',repo,common+extra),('live',live,common)]:
    for name in files:
        target=root/name
        # Every write is confined to the explicitly named project tree.
        target.resolve().relative_to(project.resolve())
        before=None
        if target.exists():
            before=digest(target)
            saved=backup/group/name; saved.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(stage/name,target)
        if digest(target)!=digest(stage/name): raise RuntimeError('Copy verification failed')
        changes.append({'file':str(target),'before':before,'after':digest(target)})

guide=project/'Alex-Desktop/ORBIT-DESKTOP.md'; shutil.copy2(stage/'ORBIT-DESKTOP.md',guide)
existing=project/'Alex-Desktop/ALEX-DESKTOP.md'
shutil.copy2(existing,backup/'ALEX-DESKTOP.md')
with existing.open('a',encoding='utf-8') as f:
    f.write('\n## Trạm chỉ huy và Vũ trụ Alex\n\nĐã thêm hai mục ở thanh bên. Xem [hướng dẫn mới](ORBIT-DESKTOP.md) để dùng quỹ đạo và camera cử chỉ. Camera mặc định tắt.\n')
for name in ['orbit-tests.json','orbit-tests.txt','preview-center.png','preview-space.png',
             'preview-space-small.png','ORBIT-DESKTOP.md','requirements-gestures.lock.txt']:
    shutil.copy2(stage/name,report/name)
(report/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
handoff=project/'ALEX-HANDOFF-CODEX-ANTIGRAVITY.md'
shutil.copy2(handoff,backup/'ALEX-HANDOFF-CODEX-ANTIGRAVITY.md')
with handoff.open('a',encoding='utf-8') as f:
    f.write(f'''\n## Bổ sung 27/10/2026 — Trạm chỉ huy và Vũ trụ Alex

Thay mục “Các cách nói đã học” trong Alex Desktop bằng Trạm chỉ huy; thêm Vũ trụ Alex.
Không xóa learned phrases. Giao diện chat/router/model/điện thoại giữ nguyên cơ chế.
Các file mới: `desktop/pet/command_center.py`, `space_view.py`, `orbit_math.py`,
`gesture_worker.py`, tích hợp qua `app_window.py`. Hướng dẫn `Alex-Desktop/ORBIT-DESKTOP.md`.

Quỹ đạo vẽ bằng QPainter, 8 hành tinh, chu kỳ theo NASA; tỷ lệ và pha minh họa, không
phải ephemeris. Kéo/cuộn chuột, chọn hành tinh, tạm dừng, tốc độ. Camera opt-in qua
QProcess riêng: chụm ngón cái-trỏ kéo xoay; hai tay mở/khép thu phóng. Rời trang,
minimize/hide đóng camera; không tự bật lại. Chỉ truyền landmarks, không lưu/gửi frame.
Thư viện MediaPipe 1.1.1 được cài vào `.venv-gestures` riêng ở live, không thay .venv pet.
Model public có provenance/hash trong ORBIT-DESKTOP.md. MediaPipe cần đọc model bằng
bytes và cwd ASCII để tránh lỗi native Unicode trên Windows; đã sửa và probe đạt.

22 tests Qt/protocol/math đạt. Render offscreen trung bình 6,26 ms, p95 7,99 ms trong
bài đo này, không phải cam kết FPS trên mọi tải máy. Model probe ảnh đen đạt, không
mở camera. Chưa thử cử chỉ tay qua camera thật. Chưa restart phiên Alex đang chạy;
phải nạp lại tiến trình để giao diện mới xuất hiện. Chưa push GitHub.

Báo cáo: `{report.relative_to(project)}`. Backup: `{backup.relative_to(project)}`.
''')
result={'report':str(report),'backup':str(backup),'guide':str(guide),'deployed':True,'restart_required':True,
        'camera_hardware_tested':False,'model_probe_passed':True}
(report/'deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
(stage/'orbit-deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
